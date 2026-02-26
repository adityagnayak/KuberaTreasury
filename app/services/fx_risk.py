"""
NexusTreasury — FX Risk Management Service (Phase 4)
Flash crash detection, VaR calculation, forward settlement adjustment.
"""

from __future__ import annotations

import math
import random
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Dict, List, Optional, Tuple

import holidays as holidays_lib

from app.core.exceptions import MarketVolatilityAlert

getcontext().prec = 28

# ─── Baseline FX rates ────────────────────────────────────────────────────────

_BASE_RATES: Dict[str, Decimal] = {
    "USD/EUR": Decimal("0.9200"),
    "USD/GBP": Decimal("0.7850"),
    "USD/JPY": Decimal("149.50"),
    "USD/CHF": Decimal("0.8950"),
    "USD/AUD": Decimal("1.5300"),
    "USD/CAD": Decimal("1.3600"),
    "EUR/GBP": Decimal("0.8532"),
    "EUR/JPY": Decimal("162.50"),
    "EUR/CHF": Decimal("0.9728"),
    "GBP/USD": Decimal("1.2739"),
    "GBP/JPY": Decimal("190.35"),
    "EUR/USD": Decimal("1.0870"),
}


# ─── Thread-safe rate store ───────────────────────────────────────────────────

class ThreadSafeRateStore:
    def __init__(self) -> None:
        self._store: dict = {}
        self._lock = threading.RLock()

    def get(self, key: str):
        with self._lock:
            return self._store.get(key)

    def set(self, key: str, value) -> None:
        with self._lock:
            self._store[key] = value

    def keys_with_prefix(self, prefix: str) -> List[str]:
        with self._lock:
            return [k for k in self._store if k.startswith(prefix)]


@dataclass
class FXRate:
    pair: str
    rate: Decimal
    timestamp: datetime
    source: str = "MockFXRateService"


class MockFXRateService:
    """Returns Decimal FX rates and stores them in the thread-safe cache."""

    def __init__(self, store: Optional[ThreadSafeRateStore] = None) -> None:
        self._store = store or ThreadSafeRateStore()
        self._preload()

    def _preload(self) -> None:
        now = datetime.utcnow()
        for pair, rate in _BASE_RATES.items():
            self._store_rate(pair, rate, now)

    def _store_rate(self, pair: str, rate: Decimal, ts: datetime) -> None:
        entry = FXRate(pair=pair, rate=rate, timestamp=ts)
        self._store.set(f"fx:{pair}:current", entry)
        self._store.set(f"fx:{pair}:{int(ts.timestamp())}", entry)

    def get_rate(self, pair: str) -> Optional[FXRate]:
        return self._store.get(f"fx:{pair}:current")

    def update_rate(
        self, pair: str, new_rate: Decimal, ts: Optional[datetime] = None
    ) -> FXRate:
        if ts is None:
            ts = datetime.utcnow()
        entry = FXRate(pair=pair, rate=new_rate, timestamp=ts)
        self._store.set(f"fx:{pair}:current", entry)
        self._store.set(f"fx:{pair}:{int(ts.timestamp())}", entry)
        return entry

    def get_rate_at(self, pair: str, ts: datetime) -> Optional[FXRate]:
        return self._store.get(f"fx:{pair}:{int(ts.timestamp())}")


# ─── VaR Calculation ─────────────────────────────────────────────────────────

def generate_historical_returns(
    pair: str, n: int = 250, seed: int = 42
) -> List[Decimal]:
    """Generate 250-day mock daily returns (fixed seed for reproducibility)."""
    rng = random.Random(seed + hash(pair) % 1000)
    return [Decimal(str(round(rng.gauss(0.0001, 0.007), 8))) for _ in range(n)]


@dataclass
class VaRResult:
    pair: str
    position_value: Decimal
    var_amount: Decimal
    confidence_level: Decimal
    holding_period_days: int
    calculation_date: date
    worst_return: Decimal
    return_index_used: int


def calculate_var(
    pair: str,
    position_value: Decimal,
    confidence: Decimal = Decimal("0.95"),
    holding_period: int = 1,
    returns: Optional[List[Decimal]] = None,
) -> VaRResult:
    """Historical simulation VaR at 95% confidence."""
    if returns is None:
        returns = generate_historical_returns(pair)

    sorted_returns = sorted(returns)
    n = len(sorted_returns)
    pct = Decimal("1") - confidence
    idx = max(0, min(int(math.floor(float(n * pct))), n - 1))

    worst_return = sorted_returns[idx]
    var_amount = (position_value * abs(worst_return)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return VaRResult(
        pair=pair,
        position_value=position_value,
        var_amount=var_amount,
        confidence_level=confidence,
        holding_period_days=holding_period,
        calculation_date=date.today(),
        worst_return=worst_return,
        return_index_used=idx,
    )


# ─── Flash Crash Detector ─────────────────────────────────────────────────────

@dataclass
class FlashCrashEvent:
    pair: str
    old_rate: Decimal
    new_rate: Decimal
    swing_pct: Decimal
    timestamp: datetime
    var_result: Optional[VaRResult] = None
    frozen_payment_ids: List[str] = field(default_factory=list)


class FlashCrashDetector:
    """
    Compares new FX rate vs rate 60 seconds ago.
    5% swing → MarketVolatilityAlert.
    20% swing → recalculate VaR and freeze pending FX payments.
    """

    SOFT_THRESHOLD = Decimal("0.05")
    HARD_THRESHOLD = Decimal("0.20")
    LOOKBACK_SECONDS = 60

    def __init__(
        self,
        fx_service: MockFXRateService,
        payment_registry: Optional[Dict[str, dict]] = None,
        threshold: Optional[Decimal] = None,
    ) -> None:
        self._fx = fx_service
        self._payment_registry = payment_registry or {}
        self._alerts: List[FlashCrashEvent] = []
        self._threshold = threshold or self.SOFT_THRESHOLD

    @property
    def alerts(self) -> List[FlashCrashEvent]:
        return self._alerts

    def check_rate_update(
        self,
        pair: str,
        new_rate: Decimal,
        now: Optional[datetime] = None,
    ) -> Optional[FlashCrashEvent]:
        if now is None:
            now = datetime.utcnow()

        old_ts = now - timedelta(seconds=self.LOOKBACK_SECONDS)
        old_entry = self._fx.get_rate_at(pair, old_ts)

        if old_entry is None:
            self._fx.update_rate(pair, new_rate, now)
            return None

        old_rate = old_entry.rate
        if old_rate == Decimal("0"):
            return None

        swing = abs(new_rate - old_rate) / old_rate

        if swing < self._threshold:
            self._fx.update_rate(pair, new_rate, now)
            return None

        event = FlashCrashEvent(
            pair=pair,
            old_rate=old_rate,
            new_rate=new_rate,
            swing_pct=swing,
            timestamp=now,
        )

        if swing >= self.HARD_THRESHOLD:
            event.var_result = calculate_var(pair, Decimal("1000000"))
            frozen = []
            for pid, pdata in self._payment_registry.items():
                if pdata.get("pair") == pair and pdata.get("status") not in (
                    "FROZEN", "FX_VOLATILITY_HOLD", "EXPORTED", "FAILED"
                ):
                    pdata["status"] = "FX_VOLATILITY_HOLD"
                    frozen.append(pid)
            event.frozen_payment_ids = frozen

        self._alerts.append(event)
        self._fx.update_rate(pair, new_rate, now)
        raise MarketVolatilityAlert(
            pair=pair,
            old_rate=old_rate,
            new_rate=new_rate,
            swing_pct=swing,
        )


# ─── Forward Settlement Adjuster ──────────────────────────────────────────────

_CURRENCY_COUNTRY_MAP = {
    "USD": "US", "EUR": "DE", "GBP": "GB",
    "JPY": "JP", "CHF": "CH", "AUD": "AU", "CAD": "CA",
}


def _get_holiday_calendar(currency: str, year: int) -> set:
    country = _CURRENCY_COUNTRY_MAP.get(currency)
    if not country:
        return set()
    try:
        cal = holidays_lib.country_holidays(country, years=year)
        return set(cal.keys()) if hasattr(cal, "keys") else set(cal)
    except Exception:
        return set()


def _is_business_day(d: date, all_holidays: set) -> bool:
    return d.weekday() < 5 and d not in all_holidays


class ForwardSettlementAdjuster:
    """Adjusts FX forward maturity dates for bank holidays."""

    def adjust(
        self,
        maturity_date: date,
        currency_pair: str,
        convention: str = "modified_following",
    ) -> date:
        ccy1, ccy2 = currency_pair.split("/")
        years = {maturity_date.year, (maturity_date + timedelta(days=10)).year}
        all_holidays: set = set()
        for y in years:
            all_holidays |= _get_holiday_calendar(ccy1, y)
            all_holidays |= _get_holiday_calendar(ccy2, y)

        if _is_business_day(maturity_date, all_holidays):
            return maturity_date

        if convention == "following":
            candidate = maturity_date + timedelta(days=1)
            while not _is_business_day(candidate, all_holidays):
                candidate += timedelta(days=1)
            return candidate

        if convention == "modified_following":
            candidate = maturity_date + timedelta(days=1)
            while not _is_business_day(candidate, all_holidays):
                candidate += timedelta(days=1)
            if candidate.month != maturity_date.month:
                candidate = maturity_date - timedelta(days=1)
                while not _is_business_day(candidate, all_holidays):
                    candidate -= timedelta(days=1)
            return candidate

        raise ValueError(f"Unknown convention: {convention}")
