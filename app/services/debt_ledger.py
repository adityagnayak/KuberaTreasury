"""
NexusTreasury — Debt & Investment Ledger Service (Phase 4)
Manages loan, deposit, FX forward, and intercompany instruments.
Enforces day-count conventions and transfer pricing arm's-length rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, getcontext
from typing import Dict, Optional

from app.core.day_count import calculate_interest, resolve_convention
from app.core.exceptions import (
    TransferPricingViolationError,
    UnsupportedConventionError,
)

getcontext().prec = 28


@dataclass
class DebtInstrument:
    instrument_id: str
    instrument_type: str  # LOAN | DEPOSIT | BOND | INTERCOMPANY
    currency: str
    principal: Decimal
    rate: Decimal  # annual rate (can be negative)
    start_date: date
    maturity_date: date
    convention_override: Optional[str] = None
    instrument_subtype: Optional[str] = None  # MM | BOND for USD disambiguation


@dataclass
class InterestResult:
    interest_amount: Decimal
    accrual_period_days: int
    convention_used: str
    principal: Decimal
    rate: Decimal
    is_negative_rate: bool


class DebtInvestmentLedger:
    """
    Manages TermLoan, MoneyMarketFund, FXForward, IntercompanyLoan instruments.
    Enforces day-count conventions, negative rate GL reversals, transfer pricing.
    """

    ARM_LENGTH_BPS = Decimal("150")  # ±150 bps from base_rate

    def __init__(self) -> None:
        self._instruments: Dict[str, DebtInstrument] = {}
        self._intercompany_positions: Dict[str, Decimal] = {}

    # ── Convention resolution ──────────────────────────────────────────────────

    def _resolve_convention(self, instrument: DebtInstrument) -> str:
        if instrument.convention_override:
            if instrument.convention_override not in (
                "ACT/360",
                "ACT/365",
                "30/360",
                "ACT/ACT",
            ):
                raise UnsupportedConventionError(instrument.convention_override)
            return instrument.convention_override
        return resolve_convention(
            instrument.currency, instrument.instrument_subtype or ""
        )

    # ── Interest calculation ───────────────────────────────────────────────────

    def calculate_interest(
        self,
        instrument: DebtInstrument,
        accrual_start: Optional[date] = None,
        accrual_end: Optional[date] = None,
    ) -> InterestResult:
        start = accrual_start or instrument.start_date
        end = accrual_end or instrument.maturity_date
        convention = self._resolve_convention(instrument)

        interest = calculate_interest(
            # FIX: Changed 'principal' to 'notional' to match core function signature
            notional=instrument.principal,
            rate=instrument.rate,
            start=start,
            end=end,
            convention=convention,
        )

        return InterestResult(
            interest_amount=interest,
            accrual_period_days=(end - start).days,
            convention_used=convention,
            principal=instrument.principal,
            rate=instrument.rate,
            is_negative_rate=instrument.rate < Decimal("0"),
        )

    # ── Instrument management ──────────────────────────────────────────────────

    def add_instrument(self, instrument: DebtInstrument) -> None:
        self._instruments[instrument.instrument_id] = instrument

    def get_instrument(self, instrument_id: str) -> Optional[DebtInstrument]:
        return self._instruments.get(instrument_id)

    # ── Intercompany netting ───────────────────────────────────────────────────

    def record_intercompany_position(self, entity_pair: str, amount: Decimal) -> None:
        current = self._intercompany_positions.get(entity_pair, Decimal("0"))
        self._intercompany_positions[entity_pair] = current + amount

    def get_intercompany_balance(self, entity_pair: str) -> Decimal:
        return self._intercompany_positions.get(entity_pair, Decimal("0"))

    # ── Transfer pricing ───────────────────────────────────────────────────────

    def validate_transfer_pricing(
        self,
        proposed_rate: Decimal,
        base_rate: Decimal,
    ) -> bool:
        """Raise TransferPricingViolationError if proposed rate is outside arm's-length range."""
        bps = self.ARM_LENGTH_BPS / Decimal("10000")
        lower = base_rate - bps
        upper = base_rate + bps
        if not (lower <= proposed_rate <= upper):
            raise TransferPricingViolationError(
                proposed_rate=proposed_rate,
                base_rate=base_rate,
                arm_length_bps=self.ARM_LENGTH_BPS,
            )
        return True
