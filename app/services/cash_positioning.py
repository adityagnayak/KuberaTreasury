"""
NexusTreasury — Cash Positioning Service (Phase 2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import FXRateNotFoundError
from app.models.entities import BankAccount
from app.models.transactions import CashPosition

getcontext().prec = 28


# ─── FX Cache ─────────────────────────────────────────────────────────────────

class FXRateCache:
    """
    Thread-safe in-memory FX rate cache.
    All rates stored as Decimal; never float.
    """

    def __init__(self) -> None:
        self._rates: Dict[str, Decimal] = {}

    def set_rate(self, from_ccy: str, to_ccy: str, rate: Decimal) -> None:
        if not isinstance(rate, Decimal):
            raise TypeError(f"FX rate must be Decimal, got {type(rate)}")
        self._rates[f"{from_ccy}:{to_ccy}"] = rate
        if rate != Decimal("0"):
            self._rates[f"{to_ccy}:{from_ccy}"] = Decimal("1") / rate

    def get_rate(self, from_ccy: str, to_ccy: str) -> Decimal:
        if from_ccy == to_ccy:
            return Decimal("1")
        raw = self._rates.get(f"{from_ccy}:{to_ccy}")
        if raw is None:
            raise FXRateNotFoundError(from_ccy, to_ccy)
        return raw

    def convert(self, amount: Decimal, from_ccy: str, to_ccy: str) -> Decimal:
        if not isinstance(amount, Decimal):
            raise TypeError(f"Amount must be Decimal, got {type(amount)}")
        return amount * self.get_rate(from_ccy, to_ccy)


# Module-level default cache instance
fx_cache = FXRateCache()


# ─── DTOs ─────────────────────────────────────────────────────────────────────

@dataclass
class CashPositionDTO:
    account_id: str
    currency: str
    as_of_date: date
    balance: Decimal
    balance_type: str   # "value_date" | "entry_date"


@dataclass
class AggregatedPosition:
    entity_id: str
    currency: str
    as_of_date: date
    total_balance: Decimal
    account_breakdown: Dict[str, Decimal]


@dataclass
class PoolMemberResult:
    account_id: str
    currency: str
    local_balance: Decimal
    base_currency_balance: Decimal
    interest_earned: Decimal


@dataclass
class PoolConfig:
    pool_id: str
    base_currency: str
    credit_rate: Decimal
    debit_rate: Decimal


@dataclass
class PoolPosition:
    pool_id: str
    base_currency: str
    as_of_date: date
    net_balance_base: Decimal
    gross_credits_base: Decimal
    gross_debits_base: Decimal
    net_interest: Decimal
    members: List[PoolMemberResult]


# ─── Currency converter ───────────────────────────────────────────────────────

class CurrencyConverter:
    def __init__(self, fx: FXRateCache) -> None:
        self._fx = fx

    def sum_in_base(
        self,
        amounts: List[Tuple[Decimal, str]],
        base_currency: str,
    ) -> Decimal:
        total = Decimal("0")
        for amount, ccy in amounts:
            if not isinstance(amount, Decimal):
                raise TypeError(f"All amounts must be Decimal; got {type(amount)}")
            total += self._fx.convert(amount, ccy, base_currency)
        return total

    @staticmethod
    def display_round(amount: Decimal) -> Decimal:
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ─── Physical Pool Calculator ─────────────────────────────────────────────────

class PhysicalPoolCalculator:
    """
    Interest earned = balance × rate / 365 (daily accrual).
    When pool net = 0 and debit_rate > credit_rate, net_interest < 0 (spread cost).
    """

    def __init__(self, config: PoolConfig, fx: FXRateCache) -> None:
        self._config = config
        self._fx = fx
        if config.debit_rate < config.credit_rate:
            raise ValueError("debit_rate must be >= credit_rate (spread must be >= 0)")

    def calculate(
        self,
        members: List[Tuple[str, str, Decimal]],
        as_of_date: date,
    ) -> PoolPosition:
        base_ccy = self._config.base_currency
        results: List[PoolMemberResult] = []
        gross_credits = Decimal("0")
        gross_debits = Decimal("0")
        credit_interest = Decimal("0")
        debit_interest = Decimal("0")

        for account_id, currency, local_balance in members:
            base_balance = self._fx.convert(local_balance, currency, base_ccy)
            if base_balance >= Decimal("0"):
                daily_interest = base_balance * self._config.credit_rate / Decimal("365")
                gross_credits += base_balance
                credit_interest += daily_interest
            else:
                daily_interest = base_balance * self._config.debit_rate / Decimal("365")
                gross_debits += base_balance
                debit_interest += daily_interest

            results.append(PoolMemberResult(
                account_id=account_id,
                currency=currency,
                local_balance=local_balance,
                base_currency_balance=base_balance,
                interest_earned=daily_interest,
            ))

        return PoolPosition(
            pool_id=self._config.pool_id,
            base_currency=base_ccy,
            as_of_date=as_of_date,
            net_balance_base=gross_credits + gross_debits,
            gross_credits_base=gross_credits,
            gross_debits_base=gross_debits,
            net_interest=credit_interest + debit_interest,
            members=results,
        )


# ─── Cash Positioning Service ─────────────────────────────────────────────────

class CashPositioningService:
    def __init__(self, session: Session, fx: FXRateCache) -> None:
        self._session = session
        self._fx = fx
        self._converter = CurrencyConverter(fx)

    def get_position(
        self,
        account_id: str,
        as_of_date: date,
        use_value_date: bool = True,
    ) -> CashPositionDTO:
        row = (
            self._session.query(CashPosition)
            .filter(
                CashPosition.account_id == account_id,
                CashPosition.position_date <= as_of_date,
            )
            .order_by(CashPosition.position_date.desc())
            .first()
        )
        account = self._session.query(BankAccount).filter_by(id=account_id).first()
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        if row is None:
            return CashPositionDTO(
                account_id=account_id,
                currency=account.currency,
                as_of_date=as_of_date,
                balance=Decimal("0"),
                balance_type="value_date" if use_value_date else "entry_date",
            )

        balance = (
            Decimal(str(row.value_date_balance))
            if use_value_date
            else Decimal(str(row.entry_date_balance))
        )
        return CashPositionDTO(
            account_id=account_id,
            currency=row.currency,
            as_of_date=row.position_date,
            balance=balance,
            balance_type="value_date" if use_value_date else "entry_date",
        )

    def get_entity_position(
        self,
        entity_id: str,
        currency: str,
        as_of_date: date,
    ) -> AggregatedPosition:
        accounts = (
            self._session.query(BankAccount)
            .filter_by(entity_id=entity_id, account_status="active")
            .all()
        )
        breakdown: Dict[str, Decimal] = {}
        amounts: List[Tuple[Decimal, str]] = []

        for acct in accounts:
            pos = self.get_position(acct.id, as_of_date)
            amounts.append((pos.balance, pos.currency))
            breakdown[acct.id] = self._fx.convert(pos.balance, pos.currency, currency)

        total = self._converter.sum_in_base(amounts, currency)
        return AggregatedPosition(
            entity_id=entity_id,
            currency=currency,
            as_of_date=as_of_date,
            total_balance=total,
            account_breakdown=breakdown,
        )

    def get_pool_position(
        self,
        pool_config: PoolConfig,
        members: List[Tuple[str, str, Decimal]],
        as_of_date: date,
    ) -> PoolPosition:
        calc = PhysicalPoolCalculator(pool_config, self._fx)
        return calc.calculate(members, as_of_date)
