"""
NexusTreasury — Phase 4 Test Suite: FX Risk, VaR, Debt Ledger, GL Engine
FIX: calculate_var uses (pair, position_value, confidence, holding_period);
     FlashCrashDetector needs explicit `now` so get_rate_at timestamp matches;
     DebtInvestmentLedger() and GLMappingEngine() take NO session arg;
     DebtInstrument/calculate_interest use different param names.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import pytest

from app.core.day_count import (
    DayCountConvention,
    calculate_interest,
    calculate_year_fraction,
)
from app.core.exceptions import (
    MarketVolatilityAlert,
    TransferPricingViolationError,
    UnbalancedJournalError,
)
from app.services.debt_ledger import DebtInstrument, DebtInvestmentLedger
from app.services.fx_risk import (
    FlashCrashDetector,
    ForwardSettlementAdjuster,
    MockFXRateService,
    ThreadSafeRateStore,
    TreasuryEvent,
    calculate_var,
)
from app.services.gl_engine import GLMappingEngine
from app.services.gl_engine import TreasuryEvent as GLEvent

# ─── VaR Tests ────────────────────────────────────────────────────────────────


def test_var_calculation_positive():
    result = calculate_var(
        pair="EUR/USD",
        position_value=Decimal("1000000.00"),
        confidence=Decimal("0.99"),
        holding_period=1,
    )
    assert result.var_amount > Decimal("0")
    assert result.confidence_level == Decimal("0.99")


def test_var_zero_position():
    result = calculate_var(
        pair="EUR/USD",
        position_value=Decimal("0"),
        confidence=Decimal("0.95"),
        holding_period=1,
    )
    assert result.var_amount == Decimal("0")


# ─── Flash Crash Tests ────────────────────────────────────────────────────────
#
# KEY FIX: MockFXRateService.get_rate_at() looks up by int(ts.timestamp()).
# check_rate_update() computes old_ts = now - 60s and looks that up.
# We must seed the rate at EXACTLY (now - 60s) using an explicit `now`.
#


def _make_detector_with_baseline(pair, baseline_rate):
    """Create detector with a baseline rate seeded at exactly now-60s."""
    store = ThreadSafeRateStore()
    fx = MockFXRateService(store=store)
    now = datetime.utcnow()
    old_time = now - timedelta(seconds=FlashCrashDetector.LOOKBACK_SECONDS)
    fx.update_rate(pair, baseline_rate, old_time)
    return fx, now


def test_flash_crash_soft_threshold():
    """A 7% move triggers MarketVolatilityAlert (soft)."""
    fx, now = _make_detector_with_baseline("EUR/USD", Decimal("1.10"))
    detector = FlashCrashDetector(fx_service=fx)
    new_rate = Decimal("1.10") * Decimal("0.93")  # -7% move > 5% threshold

    with pytest.raises(MarketVolatilityAlert) as exc_info:
        detector.check_rate_update("EUR/USD", new_rate, now=now)

    assert not exc_info.value.is_hard_crash
    assert exc_info.value.severity == "SOFT"


def test_flash_crash_hard_threshold():
    """A 25% move triggers MarketVolatilityAlert (hard crash)."""
    fx, now = _make_detector_with_baseline("EUR/USD", Decimal("1.10"))
    detector = FlashCrashDetector(fx_service=fx)
    new_rate = Decimal("1.10") * Decimal("0.70")  # -30% move > 20% hard threshold

    with pytest.raises(MarketVolatilityAlert) as exc_info:
        detector.check_rate_update("EUR/USD", new_rate, now=now)

    assert exc_info.value.is_hard_crash


def test_no_alert_for_normal_move():
    """A 1% move should not raise."""
    fx, now = _make_detector_with_baseline("EUR/USD", Decimal("1.10"))
    detector = FlashCrashDetector(fx_service=fx)
    new_rate = Decimal("1.10") * Decimal("0.99")  # -1% move < 5% threshold
    # Should not raise
    detector.check_rate_update("EUR/USD", new_rate, now=now)


def test_no_alert_without_prior_rate():
    """First-ever rate update with no history should not raise."""
    fx = MockFXRateService()
    detector = FlashCrashDetector(fx_service=fx)
    detector.check_rate_update("EUR/GBP", Decimal("0.85"))


def test_forward_settlement_business_day_adjustment():
    adjuster = ForwardSettlementAdjuster()
    christmas = date(2024, 12, 25)
    adjusted = adjuster.adjust(
        maturity_date=christmas,
        currency_pair="EUR/GBP",
        convention="modified_following",
    )
    assert adjusted.weekday() < 5
    assert adjusted >= christmas


# ─── Day Count Convention Tests ───────────────────────────────────────────────


def test_act360_calculation():
    start, end = date(2024, 1, 1), date(2024, 4, 1)  # 91 days
    yf = calculate_year_fraction(start, end, DayCountConvention.ACT_360)
    assert abs(float(yf) - 91 / 360) < 0.0001


def test_act365_calculation():
    start, end = date(2024, 1, 1), date(2024, 4, 1)
    yf = calculate_year_fraction(start, end, DayCountConvention.ACT_365)
    assert abs(float(yf) - 91 / 365) < 0.0001


def test_30_360_calculation():
    start, end = date(2024, 1, 1), date(2024, 7, 1)
    yf = calculate_year_fraction(start, end, DayCountConvention.THIRTY_360)
    assert abs(float(yf) - 0.5) < 0.001


def test_interest_calculation_decimal():
    interest = calculate_interest(
        notional=Decimal("1000000.00"),
        rate=Decimal("0.05"),
        start_date=date(2024, 1, 1),
        end_date=date(2025, 1, 1),
        convention=DayCountConvention.ACT_365,
    )
    assert isinstance(interest, Decimal)
    assert interest > Decimal("0")


def test_negative_rate_interest_calculation():
    interest = calculate_interest(
        notional=Decimal("500000.00"),
        rate=Decimal("-0.005"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 7, 1),
        convention=DayCountConvention.ACT_360,
    )
    assert interest < Decimal("0")


# ─── Debt Ledger Tests ────────────────────────────────────────────────────────
# DebtInvestmentLedger() takes NO arguments — it's a pure in-memory ledger.
# Instruments are DebtInstrument dataclasses, not ORM models.


def test_interest_accrual_calculation():
    ledger = DebtInvestmentLedger()
    instrument = DebtInstrument(
        instrument_id="LOAN-001",
        instrument_type="loan",
        currency="EUR",
        principal=Decimal("1000000.00"),
        rate=Decimal("0.04"),
        start_date=date(2024, 1, 1),
        maturity_date=date(2025, 1, 1),
    )
    ledger.add_instrument(instrument)
    result = ledger.calculate_interest(instrument, accrual_end=date(2024, 7, 1))
    assert result.interest_amount > Decimal("0")
    assert isinstance(result.interest_amount, Decimal)


def test_transfer_pricing_violation():
    """A loan rate >150bps above base must raise TransferPricingViolationError."""
    ledger = DebtInvestmentLedger()
    with pytest.raises(TransferPricingViolationError):
        # proposed=9%, base=4% → 500bps spread, exceeds 150bps limit
        ledger.validate_transfer_pricing(
            proposed_rate=Decimal("0.09"),
            base_rate=Decimal("0.04"),
        )


def test_transfer_pricing_within_arm_length():
    """A rate within 150bps of base should pass validation."""
    ledger = DebtInvestmentLedger()
    # proposed=4%, base=3.5% → 50bps spread, within 150bps
    ledger.validate_transfer_pricing(
        proposed_rate=Decimal("0.04"),
        base_rate=Decimal("0.035"),
    )


def test_intercompany_netting():
    ledger = DebtInvestmentLedger()
    ledger.record_intercompany_position("ParentCo:SubA", Decimal("500000.00"))
    ledger.record_intercompany_position("ParentCo:SubA", Decimal("-200000.00"))
    balance = ledger.get_intercompany_balance("ParentCo:SubA")
    assert balance == Decimal("300000.00")


# ─── GL Engine Tests ──────────────────────────────────────────────────────────
# GLMappingEngine() takes NO arguments.
# Use post_journal(TreasuryEvent(...)) not post_event().


def test_gl_journal_must_balance():
    engine = GLMappingEngine()
    event = GLEvent(
        event_id="EVT-001",
        event_type="INTEREST_ACCRUAL",
        amount=Decimal("5000.00"),
        currency="EUR",
        metadata={},
    )
    entry = engine.post_journal(event)
    total_debits = sum(l.debit for l in entry.lines)
    total_credits = sum(l.credit for l in entry.lines)
    assert total_debits == total_credits


def test_unbalanced_journal_rejected():
    """_assert_balanced should raise if we manually create unbalanced lines."""
    from app.services.gl_engine import JournalLine

    engine = GLMappingEngine()
    lines = [
        JournalLine(
            account_code="1000",
            account_name="Bank",
            debit=Decimal("1000"),
            credit=Decimal("0"),
            currency="EUR",
        ),
        JournalLine(
            account_code="4000",
            account_name="Income",
            debit=Decimal("0"),
            credit=Decimal("999"),
            currency="EUR",
        ),
    ]
    with pytest.raises(UnbalancedJournalError):
        engine._assert_balanced(lines)


def test_negative_interest_gl_balances():
    engine = GLMappingEngine()
    event = GLEvent(
        event_id="EVT-002",
        event_type="INTEREST_ACCRUAL",
        amount=Decimal("-500.00"),
        currency="EUR",
        metadata={"negative_rate": True},
    )
    entry = engine.post_journal(event)
    total_debits = sum(l.debit for l in entry.lines)
    total_credits = sum(l.credit for l in entry.lines)
    assert total_debits == total_credits


def test_fx_revaluation_journal_posted():
    engine = GLMappingEngine()
    event = GLEvent(
        event_id="EVT-003",
        event_type="FX_REVALUATION",
        amount=Decimal("2500.00"),
        currency="USD",
        metadata={"gain_loss": Decimal("2500.00"), "direction": "GAIN"},
    )
    entry = engine.post_journal(event)
    account_names = [l.account_name for l in entry.lines]
    assert any("FX" in n or "Revaluation" in n or "PnL" in n for n in account_names)
    total_debits = sum(l.debit for l in entry.lines)
    total_credits = sum(l.credit for l in entry.lines)
    assert total_debits == total_credits


def test_payment_sent_journal():
    engine = GLMappingEngine()
    event = GLEvent(
        event_id="EVT-004",
        event_type="PAYMENT_SENT",
        amount=Decimal("10000.00"),
        currency="EUR",
        metadata={},
    )
    entry = engine.post_journal(event)
    total_debits = sum(l.debit for l in entry.lines)
    total_credits = sum(l.credit for l in entry.lines)
    assert total_debits == total_credits
