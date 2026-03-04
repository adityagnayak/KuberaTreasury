"""Tests for Intercompany service — TP validation boundaries, CIR thresholds, ageing."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TransferPricingError
from app.models import Tenant
from app.services.intercompany_service import (
    IntercompanyService,
    IntercompanyTransactionCreate,
)


def _svc(db, tenant_id, user_id) -> IntercompanyService:
    return IntercompanyService(db, tenant_id, user_id)


def _tx_payload(
    contracted_bps: Decimal | None = None,
    benchmark_bps: Decimal | None = None,
    tp_just: str | None = None,
    due_date: date | None = None,
) -> IntercompanyTransactionCreate:
    return IntercompanyTransactionCreate(
        counterparty_entity_name="KuberaTreasury Holdings BV",
        counterparty_entity_id="NL-KTH-001",
        transaction_type="loan",
        transaction_date=date(2026, 1, 15),
        due_date=due_date or date(2026, 7, 15),
        principal_amount=Decimal("500000"),
        currency_code="GBP",
        contracted_rate_bps=contracted_bps,
        benchmark_rate_bps=benchmark_bps,
        tp_justification=tp_just,
    )


# ─────────────────────────────────────────────── TP validation ─────────────────

@pytest.mark.asyncio
async def test_tp_within_tolerance_passes(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    """Contracted rate within ±150bps of benchmark should not raise."""
    svc = _svc(db, tenant_id, user_id)
    tx = await svc.create_transaction(
        _tx_payload(contracted_bps=Decimal("300"), benchmark_bps=Decimal("250"))
    )  # variance = 50bps — within 150bps
    assert tx.tp_flag_raised is False
    assert tx.rate_variance_bps == Decimal("50")


@pytest.mark.asyncio
async def test_tp_exactly_at_150bps_passes(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    """Variance of exactly 150bps is within tolerance (≤ not <)."""
    svc = _svc(db, tenant_id, user_id)
    tx = await svc.create_transaction(
        _tx_payload(contracted_bps=Decimal("400"), benchmark_bps=Decimal("250"))
    )  # variance = 150bps exactly
    assert tx.tp_flag_raised is False


@pytest.mark.asyncio
async def test_tp_above_150bps_raises(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    """Variance of 151bps must raise TransferPricingError (TIOPA 2010 s.147)."""
    svc = _svc(db, tenant_id, user_id)
    with pytest.raises(TransferPricingError) as exc_info:
        await svc.create_transaction(
            _tx_payload(contracted_bps=Decimal("401"), benchmark_bps=Decimal("250"))
        )  # variance = 151bps > 150bps
    assert "150" in str(exc_info.value) or "arm" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_tp_no_rates_bypasses_validation(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    """Transaction with no rates should be created without TP check."""
    svc = _svc(db, tenant_id, user_id)
    tx = await svc.create_transaction(_tx_payload())
    assert tx.tp_flag_raised is False
    assert tx.rate_variance_bps is None


# ─────────────────────────────────────────────── matching ──────────────────────

@pytest.mark.asyncio
async def test_match_transaction(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    tx = await svc.create_transaction(_tx_payload())
    matched = await svc.match_transaction(tx.transaction_id)
    assert matched.is_matched is True
    assert matched.matched_at == date.today()


@pytest.mark.asyncio
async def test_list_unmatched(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    tx1 = await svc.create_transaction(_tx_payload())
    tx2 = await svc.create_transaction(_tx_payload())
    await svc.match_transaction(tx1.transaction_id)
    unmatched = await svc.list_transactions(matched=False)
    ids = [t.transaction_id for t in unmatched]
    assert tx1.transaction_id not in ids
    assert tx2.transaction_id in ids


# ─────────────────────────────────────────────── ageing ────────────────────────

@pytest.mark.asyncio
async def test_ageing_buckets_correctly(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    ref = date(2026, 6, 1)

    # 0-30 days overdue: due 2026-05-15 → 17 days
    await svc.create_transaction(_tx_payload(due_date=date(2026, 5, 15)))
    # 31-60 days overdue: due 2026-04-20 → 42 days
    await svc.create_transaction(_tx_payload(due_date=date(2026, 4, 20)))
    # 91 days overdue: due 2026-03-2 → 91 days
    await svc.create_transaction(_tx_payload(due_date=date(2026, 3, 2)))

    report = await svc.ageing_report(ref)
    bucket_map = {b.bucket: b for b in report.buckets}
    assert bucket_map["0-30"].count >= 1
    assert bucket_map["31-60"].count >= 1
    assert bucket_map["90+"].count >= 1


# ─────────────────────────────────────────────── CIR ──────────────────────────

@pytest.mark.asyncio
async def test_cir_below_alert_threshold(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    summary = await svc.calculate_cir(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        gross_interest_expense=Decimal("1_000_000"),
        gross_interest_income=Decimal("200_000"),
        restricted_amount=None,
    )
    # Net = 800k < 1.5M alert threshold
    assert summary.alert_triggered is False
    assert summary.hard_flag_triggered is False
    assert summary.net_interest_expense == Decimal("800000")


@pytest.mark.asyncio
async def test_cir_alert_at_1_5m(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    summary = await svc.calculate_cir(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        gross_interest_expense=Decimal("1_700_000"),
        gross_interest_income=Decimal("100_000"),
        restricted_amount=None,
    )
    # Net = 1.6M ≥ 1.5M → alert but < 2M hard flag
    assert summary.alert_triggered is True
    assert summary.hard_flag_triggered is False


@pytest.mark.asyncio
async def test_cir_hard_flag_at_2m(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    summary = await svc.calculate_cir(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        gross_interest_expense=Decimal("2_200_000"),
        gross_interest_income=Decimal("100_000"),
        restricted_amount=Decimal("200_000"),
    )
    # Net = 2.1M ≥ 2M → hard flag
    assert summary.hard_flag_triggered is True
    assert summary.restricted_amount == Decimal("200000")


@pytest.mark.asyncio
async def test_cir_restriction_id_is_uuid(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    summary = await svc.calculate_cir(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        gross_interest_expense=Decimal("500_000"),
        gross_interest_income=Decimal("0"),
    )
    assert summary.restriction_id is not None
    assert isinstance(summary.restriction_id, uuid.UUID)
