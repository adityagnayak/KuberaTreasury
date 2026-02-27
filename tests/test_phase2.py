"""
NexusTreasury — Phase 2 Test Suite: Cash Positioning & Liquidity Forecasting
FIX: net_interest (not net_interest_base), entry_date_balance (not available_balance),
     ForecastEntryInput list API, session.flush() for entity.id.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.entities import BankAccount, Entity
from app.models.forecasts import ForecastEntry
from app.models.transactions import CashPosition
from app.services.cash_positioning import (
    CashPositioningService,
    CurrencyConverter,
    FXRateCache,
    PhysicalPoolCalculator,
    PoolConfig,
)
from app.services.forecasting import ForecastEntryInput, LiquidityForecastingService


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def eur_entity(db_session):
    entity = Entity(name="Pool Corp", entity_type="parent", base_currency="EUR")
    db_session.add(entity)
    db_session.flush()
    db_session.commit()
    return entity


@pytest.fixture
def accounts(db_session, eur_entity):
    ibans = [
        ("DE89370400440532013100", "EUR"),
        ("GB29NWBK60161331926819", "GBP"),
        ("US12345678901234567890", "USD"),
    ]
    result = []
    for iban, ccy in ibans:
        a = BankAccount(
            entity_id=eur_entity.id,
            iban=iban,
            bic="COBADEFFXXX",
            currency=ccy,
            overdraft_limit=Decimal("10000.00"),
        )
        db_session.add(a)
        result.append(a)
    db_session.commit()
    for a in result:
        db_session.refresh(a)
    return result


@pytest.fixture
def positioning_service(db_session, mock_fx_cache):
    return CashPositioningService(db_session, mock_fx_cache)


@pytest.fixture
def forecasting_service(db_session):
    return LiquidityForecastingService(db_session)


# ─── Cash Positioning Tests ───────────────────────────────────────────────────


def test_cash_positions_created_for_accounts(db_session, accounts):
    today = date.today()
    for acct in accounts:
        pos = CashPosition(
            account_id=acct.id,
            position_date=today,
            value_date_balance=Decimal("1000.00"),
            entry_date_balance=Decimal("1000.00"),
            currency=acct.currency,
        )
        db_session.add(pos)
    db_session.commit()

    positions = db_session.query(CashPosition).filter_by(position_date=today).all()
    assert len(positions) == 3
    for pos in positions:
        assert pos.value_date_balance == Decimal("1000.00")


def test_negative_balance_stored_correctly(db_session, accounts):
    today = date.today()
    acct = accounts[0]
    pos = CashPosition(
        account_id=acct.id,
        position_date=today,
        value_date_balance=Decimal("-5000.00"),
        entry_date_balance=Decimal("-5000.00"),
        currency=acct.currency,
    )
    db_session.add(pos)
    db_session.commit()
    db_session.refresh(pos)
    assert pos.value_date_balance == Decimal("-5000.00")


def test_physical_pool_spread_net_positive():
    """debit_rate > credit_rate: bank earns net spread when pool is balanced."""
    config = PoolConfig(
        pool_id="POOL-001",
        base_currency="EUR",
        credit_rate=Decimal("0.03"),
        debit_rate=Decimal("0.05"),
    )
    fx = FXRateCache()
    fx.set_rate("EUR", "EUR", Decimal("1.0"))

    calc = PhysicalPoolCalculator(config, fx)
    members = [
        ("ACC-001", "EUR", Decimal("500000.00")),
        ("ACC-002", "EUR", Decimal("-200000.00")),
    ]
    result = calc.calculate(members, date.today())

    assert result.gross_credits_base > Decimal("0")
    assert result.gross_debits_base < Decimal("0")
    assert result.net_interest != Decimal("0")  # FIX: was net_interest_base


def test_physical_pool_zero_debit_members():
    """A pool with only credit balances has zero debit interest."""
    config = PoolConfig(
        pool_id="POOL-002",
        base_currency="EUR",
        credit_rate=Decimal("0.02"),
        debit_rate=Decimal("0.04"),
    )
    fx = FXRateCache()
    fx.set_rate("EUR", "EUR", Decimal("1.0"))

    calc = PhysicalPoolCalculator(config, fx)
    result = calc.calculate([("ACC-001", "EUR", Decimal("1000000.00"))], date.today())

    assert result.gross_debits_base == Decimal("0")
    assert result.gross_credits_base == Decimal("1000000.00")


def test_currency_converter_same_currency(mock_fx_cache):
    mock_fx_cache.set_rate("EUR", "EUR", Decimal("1.0"))
    result = mock_fx_cache.convert(Decimal("500.00"), "EUR", "EUR")
    assert result == Decimal("500.00")


def test_currency_converter_known_pair(mock_fx_cache):
    result = mock_fx_cache.convert(Decimal("100.00"), "USD", "EUR")
    assert result > Decimal("0")


def test_currency_converter_sum_in_base(mock_fx_cache):
    converter = CurrencyConverter(mock_fx_cache)
    total = converter.sum_in_base(
        [(Decimal("1000.00"), "EUR"), (Decimal("1000.00"), "USD")], "EUR"
    )
    assert total > Decimal("0")


# ─── Liquidity Forecasting Tests ──────────────────────────────────────────────


def test_forecast_ingestion_and_retrieval(db_session, accounts, forecasting_service):
    acct = accounts[0]
    tomorrow = date.today() + timedelta(days=1)
    entry = ForecastEntryInput(
        account_id=acct.id,
        currency="EUR",
        expected_date=tomorrow,
        forecast_amount=Decimal("20000.00"),
        description="Expected payment",
    )
    forecasting_service.ingest_forecast([entry])

    rows = db_session.query(ForecastEntry).filter_by(account_id=acct.id).all()
    assert len(rows) == 1
    assert rows[0].forecast_amount == Decimal("20000.00")


def test_multiple_forecasts_ingested(db_session, accounts, forecasting_service):
    acct = accounts[0]
    entries = [
        ForecastEntryInput(
            account_id=acct.id,
            currency="EUR",
            expected_date=date.today() + timedelta(days=i),
            forecast_amount=Decimal("1000.00") * i,
            description=f"Day {i}",
        )
        for i in range(1, 4)
    ]
    forecasting_service.ingest_forecast(entries)
    rows = db_session.query(ForecastEntry).filter_by(account_id=acct.id).all()
    assert len(rows) == 3


def test_reconcile_actuals_returns_report(db_session, accounts, forecasting_service):
    acct = accounts[0]
    forecasting_service.ingest_forecast(
        [
            ForecastEntryInput(
                account_id=acct.id,
                currency="EUR",
                expected_date=date.today(),
                forecast_amount=Decimal("5000.00"),
                description="Test",
            )
        ]
    )
    report = forecasting_service.reconcile_actuals(date.today())
    assert report is not None
    assert hasattr(report, "matched")
    assert hasattr(report, "unmatched_forecasts")


def test_variance_report_aggregation(db_session, accounts, forecasting_service):
    from_date = date.today() - timedelta(days=3)
    for acct in accounts[:2]:
        for offset in range(3):
            forecasting_service.ingest_forecast(
                [
                    ForecastEntryInput(
                        account_id=acct.id,
                        currency="EUR",
                        expected_date=from_date + timedelta(days=offset),
                        forecast_amount=Decimal("1000.00"),
                        description="bulk",
                    )
                ]
            )
    report = forecasting_service.get_variance_report(
        from_date=from_date, to_date=date.today()
    )
    assert report is not None
    assert report.total_forecast >= Decimal("0")


def test_forecast_decimal_type_enforced(db_session, accounts, forecasting_service):
    acct = accounts[0]
    entry = ForecastEntryInput(
        account_id=acct.id,
        currency="EUR",
        expected_date=date.today(),
        forecast_amount=1000.0,
        description="bad type",  # float, not Decimal
    )
    with pytest.raises(TypeError):
        forecasting_service.ingest_forecast([entry])
