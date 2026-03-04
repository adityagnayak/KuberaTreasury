"""Tests for Accounting Period Manager — lifecycle, authority controls, CT600, year-end."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError, PeriodClosedError
from app.models import AccountingPeriod, Tenant
from app.services.accounting_period_service import (
    AccountingPeriodCreate,
    AccountingPeriodService,
    HardCloseRequest,
    ReopenRequest,
    YearEndRolloverRequest,
    _compute_tax_dates,
)


def _svc(db, tenant_id, user_id, roles=None) -> AccountingPeriodService:
    return AccountingPeriodService(db, tenant_id, user_id, roles or [])


def _period_payload(
    name: str = "Jan 2026",
    start: date = date(2026, 1, 1),
    end: date = date(2026, 1, 31),
    is_year_end: bool = False,
    large_co: bool = False,
) -> AccountingPeriodCreate:
    return AccountingPeriodCreate(
        period_name=name,
        period_type="monthly",
        period_start=start,
        period_end=end,
        is_year_end=is_year_end,
        is_large_company_for_ct=large_co,
    )


# ─────────────────────────────────────────────── creation ──────────────────────


@pytest.mark.asyncio
async def test_create_period(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    p = await svc.create_period(_period_payload())
    assert p.period_name == "Jan 2026"
    assert p.status == "open"
    assert p.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_period_end_before_start_raises():
    with pytest.raises(Exception):  # Pydantic validation
        AccountingPeriodCreate(
            period_name="Bad",
            period_type="monthly",
            period_start=date(2026, 2, 1),
            period_end=date(2026, 1, 31),  # end before start
        )


@pytest.mark.asyncio
async def test_get_period(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    created = await svc.create_period(_period_payload())
    fetched = await svc.get_period(created.period_id)
    assert fetched.period_id == created.period_id


@pytest.mark.asyncio
async def test_get_nonexistent_raises(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    with pytest.raises(NotFoundError):
        await svc.get_period(uuid.uuid4())


# ─────────────────────────────────────────────── status transitions ────────────


@pytest.mark.asyncio
async def test_soft_close_requires_treasury_manager(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id, roles=[])  # no roles
    p = await svc.create_period(
        _period_payload("Feb 2026", date(2026, 2, 1), date(2026, 2, 28))
    )
    with pytest.raises(PermissionDeniedError):
        await svc.soft_close(p.period_id)


@pytest.mark.asyncio
async def test_soft_close_succeeds_with_treasury_manager(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id, roles=["treasury_manager"])
    p = await svc.create_period(
        _period_payload("Mar 2026", date(2026, 3, 1), date(2026, 3, 31))
    )
    closed = await svc.soft_close(p.period_id)
    assert closed.status == "soft_closed"


@pytest.mark.asyncio
async def test_hard_close_requires_system_admin(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id, roles=["treasury_manager"])  # not system_admin
    p = await svc.create_period(
        _period_payload("Apr 2026", date(2026, 4, 1), date(2026, 4, 30))
    )
    with pytest.raises(PermissionDeniedError):
        await svc.hard_close(
            p.period_id, HardCloseRequest(close_reason="Period closed for audit.")
        )


@pytest.mark.asyncio
async def test_hard_close_succeeds_with_system_admin(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id, roles=["system_admin"])
    p = await svc.create_period(
        _period_payload("May 2026", date(2026, 5, 1), date(2026, 5, 31))
    )
    closed = await svc.hard_close(
        p.period_id, HardCloseRequest(close_reason="Audit complete.")
    )
    assert closed.status == "hard_closed"
    assert closed.hard_closed_by_user_id == user_id


@pytest.mark.asyncio
async def test_reopen_requires_system_admin(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    admin_svc = _svc(db, tenant_id, user_id, roles=["system_admin"])
    p = await admin_svc.create_period(
        _period_payload("Jun 2026", date(2026, 6, 1), date(2026, 6, 30))
    )
    await admin_svc.hard_close(p.period_id, HardCloseRequest(close_reason="Closed."))
    # Non-admin cannot reopen
    user_svc = _svc(db, tenant_id, user_id, roles=["treasury_manager"])
    with pytest.raises(PermissionDeniedError):
        await user_svc.reopen_period(
            p.period_id, ReopenRequest(reopen_reason="Needs correction for audit.")
        )


@pytest.mark.asyncio
async def test_reopen_succeeds_with_system_admin(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id, roles=["system_admin"])
    p = await svc.create_period(
        _period_payload("Jul 2026", date(2026, 7, 1), date(2026, 7, 31))
    )
    await svc.hard_close(p.period_id, HardCloseRequest(close_reason="Closed."))
    reopened = await svc.reopen_period(
        p.period_id,
        ReopenRequest(reopen_reason="Error found in payroll accrual; approved by CFO."),
    )
    assert reopened.status == "open"


@pytest.mark.asyncio
async def test_soft_close_already_closed_raises(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id, roles=["treasury_manager", "system_admin"])
    p = await svc.create_period(
        _period_payload("Aug 2026", date(2026, 8, 1), date(2026, 8, 31))
    )
    await svc.soft_close(p.period_id)
    with pytest.raises(PeriodClosedError):
        await svc.soft_close(p.period_id)


# ─────────────────────────────────────────────── CT600 date calculation ────────


@pytest.mark.asyncio
async def test_ct600_nine_months_plus_one_day():
    """CT600 due: period_end + 9 months + 1 day (standard)."""
    ct600, _ = _compute_tax_dates(date(2026, 3, 31), large_company=False)
    assert ct600 == date(2026, 12, 32 - 1) or ct600 == date(2027, 1, 1)
    # 31 March + 9 months = 31 December + 1 day = 1 January 2027
    assert ct600 == date(2027, 1, 1)


@pytest.mark.asyncio
async def test_ct600_year_end_31_dec():
    ct600, _ = _compute_tax_dates(date(2026, 12, 31), large_company=False)
    # Dec + 9 months = Sep + 1 day = 1 Oct 2027
    assert ct600 == date(2027, 10, 1)


@pytest.mark.asyncio
async def test_qip_dates_for_large_company():
    _, qips = _compute_tax_dates(date(2026, 12, 31), large_company=True)
    assert len(qips) == 4


@pytest.mark.asyncio
async def test_no_qip_for_standard_company():
    _, qips = _compute_tax_dates(date(2026, 12, 31), large_company=False)
    assert qips == []


@pytest.mark.asyncio
async def test_ct_dates_via_service_static_method():
    result = AccountingPeriodService.compute_ct_dates(
        date(2026, 3, 31), is_large_company=False
    )
    assert result.ct600_due_date == date(2027, 1, 1)


@pytest.mark.asyncio
async def test_ct_dates_large_company_returns_four_qips():
    result = AccountingPeriodService.compute_ct_dates(
        date(2026, 12, 31), is_large_company=True
    )
    assert len(result.qip_due_dates) == 4


# ─────────────────────────────────────────────── CT600 on period create ────────


@pytest.mark.asyncio
async def test_period_stores_ct600_due_date(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    p = await svc.create_period(
        _period_payload("FY-2026", date(2026, 1, 1), date(2026, 12, 31))
    )
    # Dec 31 + 9 months + 1 day = Oct 1 2027
    assert p.ct600_due_date == date(2027, 10, 1)


# ─────────────────────────────────────────────── list / filter ─────────────────


@pytest.mark.asyncio
async def test_list_periods_filter_by_status(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id, roles=["treasury_manager"])
    p1 = await svc.create_period(
        _period_payload("P1", date(2026, 1, 1), date(2026, 1, 31))
    )
    p2 = await svc.create_period(
        _period_payload("P2", date(2026, 2, 1), date(2026, 2, 28))
    )
    await svc.soft_close(p1.period_id)
    open_periods = await svc.list_periods(status="open")
    open_ids = [p.period_id for p in open_periods]
    assert p1.period_id not in open_ids
    assert p2.period_id in open_ids
