"""Tests for IFRS 9 Hedge Accounting — designation, effectiveness, OCI, de-designation."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import HedgeEffectivenessError
from app.models import AccountingPeriod, ChartOfAccount, Tenant
from app.services.hedge_service import (
    DeDesignationUpdate,
    EffectivenessTestCreate,
    HedgeAccountingService,
    HedgeDesignationCreate,
    OciReclassificationCreate,
)


def _svc(db, tenant_id, user_id) -> HedgeAccountingService:
    return HedgeAccountingService(db, tenant_id, user_id)


def _designation_payload(
    hedge_type: str = "cash_flow",
    method: str = "dollar_offset",
    ratio: Decimal = Decimal("1.0"),
) -> HedgeDesignationCreate:
    return HedgeDesignationCreate(
        hedge_reference=f"HE-{uuid.uuid4().hex[:6]}",
        hedge_type=hedge_type,
        hedging_instrument_description="Interest rate swap — pay fixed 3M SONIA +50bps",
        hedged_item_description="Floating rate loan GBP 5M, SONIA +50bps",
        risk_component="Interest rate risk — SONIA benchmark",
        hedge_ratio=ratio,
        designation_date=date(2026, 1, 1),
        prospective_method=method,
    )


# ─────────────────────────────────────────────── designation ───────────────────


@pytest.mark.asyncio
async def test_designate_creates_hedge(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    assert hd.is_active is True
    assert hd.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_designation_embeds_tax_note(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    assert "corporation tax" in hd.tax_note.lower()


@pytest.mark.asyncio
async def test_hedge_ratio_must_be_between_0_and_1():
    with pytest.raises(Exception):  # pydantic validation error
        HedgeDesignationCreate(
            hedge_reference="HE-BAD",
            hedge_type="fair_value",
            hedging_instrument_description="FX Forward GBP/USD 1M",
            hedged_item_description="USD payable invoice",
            risk_component="FX risk USD",
            hedge_ratio=Decimal("1.5"),  # invalid: > 1
            designation_date=date(2026, 1, 1),
            prospective_method="dollar_offset",
        )


@pytest.mark.asyncio
async def test_list_designations_active_only(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    active = await svc.designate(_designation_payload())
    inactive = await svc.designate(_designation_payload())
    await svc.de_designate(
        inactive.hedge_id,
        DeDesignationUpdate(
            de_designation_date=date(2026, 3, 1),
            de_designation_reason="Hedged item settled early.",
            cumulative_oci_treatment="Reclassified to P&L in March 2026.",
        ),
    )
    active_list = await svc.list_designations(active_only=True)
    ids = [h.hedge_id for h in active_list]
    assert active.hedge_id in ids
    assert inactive.hedge_id not in ids


# ─────────────────────────────────────────────── effectiveness ─────────────────


@pytest.mark.asyncio
async def test_retrospective_pass_at_100_percent(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id, open_period
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    result = await svc.run_effectiveness_test(
        hd.hedge_id,
        EffectivenessTestCreate(
            period_id=open_period.period_id,
            test_type="retrospective",
            method="dollar_offset",
            instrument_fair_value_change=Decimal("1000"),
            hedged_item_fair_value_change=Decimal("-1000"),
        ),
    )
    assert result.passed is True
    assert result.effectiveness_ratio == Decimal("1")


@pytest.mark.asyncio
async def test_retrospective_pass_at_lower_band_80_percent(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id, open_period
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    result = await svc.run_effectiveness_test(
        hd.hedge_id,
        EffectivenessTestCreate(
            period_id=open_period.period_id,
            test_type="retrospective",
            method="dollar_offset",
            instrument_fair_value_change=Decimal("800"),
            hedged_item_fair_value_change=Decimal("-1000"),
        ),
    )
    assert result.passed is True


@pytest.mark.asyncio
async def test_retrospective_pass_at_upper_band_125_percent(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id, open_period
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    result = await svc.run_effectiveness_test(
        hd.hedge_id,
        EffectivenessTestCreate(
            period_id=open_period.period_id,
            test_type="retrospective",
            method="dollar_offset",
            instrument_fair_value_change=Decimal("1250"),
            hedged_item_fair_value_change=Decimal("-1000"),
        ),
    )
    assert result.passed is True


@pytest.mark.asyncio
async def test_retrospective_fails_below_80_percent(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id, open_period
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    with pytest.raises(HedgeEffectivenessError) as exc_info:
        await svc.run_effectiveness_test(
            hd.hedge_id,
            EffectivenessTestCreate(
                period_id=open_period.period_id,
                test_type="retrospective",
                method="dollar_offset",
                instrument_fair_value_change=Decimal("700"),  # 70% < 80%
                hedged_item_fair_value_change=Decimal("-1000"),
            ),
        )
    assert (
        "qualifying range" in str(exc_info.value).lower()
        or "effectiveness" in str(exc_info.value).lower()
    )


@pytest.mark.asyncio
async def test_retrospective_fails_above_125_percent(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id, open_period
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    with pytest.raises(HedgeEffectivenessError):
        await svc.run_effectiveness_test(
            hd.hedge_id,
            EffectivenessTestCreate(
                period_id=open_period.period_id,
                test_type="retrospective",
                method="dollar_offset",
                instrument_fair_value_change=Decimal("1300"),  # 130% > 125%
                hedged_item_fair_value_change=Decimal("-1000"),
            ),
        )


@pytest.mark.asyncio
async def test_prospective_test_always_passes(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id, open_period
):
    """IFRS 9 §B6.4.1: prospective test is qualitative, no numeric threshold."""
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    result = await svc.run_effectiveness_test(
        hd.hedge_id,
        EffectivenessTestCreate(
            period_id=open_period.period_id,
            test_type="prospective",
            method="dollar_offset",
            instrument_fair_value_change=Decimal(
                "600"
            ),  # 60% — would fail retrospective
            hedged_item_fair_value_change=Decimal("-1000"),
        ),
    )
    assert result.passed is True  # prospective is always qualitative


# ─────────────────────────────────────────────── de-designation ────────────────


@pytest.mark.asyncio
async def test_de_designate_sets_inactive(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    updated = await svc.de_designate(
        hd.hedge_id,
        DeDesignationUpdate(
            de_designation_date=date(2026, 6, 30),
            de_designation_reason="Hedged item sold; relationship no longer valid.",
            cumulative_oci_treatment="Cumulative OCI of £12,500 reclassified to P&L June 2026.",
        ),
    )
    assert updated.is_active is False
    assert updated.de_designation_reason is not None


@pytest.mark.asyncio
async def test_de_designate_twice_raises(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    hd = await svc.designate(_designation_payload())
    payload = DeDesignationUpdate(
        de_designation_date=date(2026, 6, 30),
        de_designation_reason="Reason",
        cumulative_oci_treatment="OCI treatment.",
    )
    await svc.de_designate(hd.hedge_id, payload)
    with pytest.raises(ValueError, match="already"):
        await svc.de_designate(hd.hedge_id, payload)


# ─────────────────────────────────────────────── hedge register ────────────────


@pytest.mark.asyncio
async def test_hedge_register_returns_list(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    await svc.designate(_designation_payload("fair_value"))
    register = await svc.get_hedge_register()
    assert isinstance(register, list)
    assert len(register) >= 1
    assert "tax_note" in register[0]
