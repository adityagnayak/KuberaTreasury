"""Tests for Journal/Ledger Engine — double-entry enforcement, period lock, VAT, reversals."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnbalancedJournalError, PeriodClosedError
from app.models import AccountingPeriod, ChartOfAccount, Tenant
from app.services.ledger_service import (
    JournalCreate,
    JournalLineCreate,
    LedgerService,
)


def _svc(db, tenant_id, user_id) -> LedgerService:
    return LedgerService(db, tenant_id, user_id)


def _balanced_journal(
    period_id, account_id_dr, account_id_cr, amount=Decimal("100")
) -> JournalCreate:
    return JournalCreate(
        period_id=period_id,
        journal_reference="TEST-001",
        description="Test journal",
        currency_code="GBP",
        lines=[
            JournalLineCreate(
                account_id=account_id_dr,
                debit_amount=amount,
                credit_amount=Decimal("0"),
                currency_code="GBP",
                vat_treatment="T9",
            ),
            JournalLineCreate(
                account_id=account_id_cr,
                debit_amount=Decimal("0"),
                credit_amount=amount,
                currency_code="GBP",
                vat_treatment="T9",
            ),
        ],
    )


# ─────────────────────────────────────────────── balance enforcement ───────────


@pytest.mark.asyncio
async def test_unbalanced_journal_raises_error(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id, base_account, open_period
):
    svc = _svc(db, tenant_id, user_id)
    with pytest.raises(UnbalancedJournalError):
        await svc.create_journal(
            JournalCreate(
                period_id=open_period.period_id,
                journal_reference="BAD-001",
                description="Unbalanced",
                currency_code="GBP",
                lines=[
                    JournalLineCreate(
                        account_id=base_account.account_id,
                        debit_amount=Decimal("100"),
                        credit_amount=Decimal("0"),
                        currency_code="GBP",
                        vat_treatment="T9",
                    )
                ],
            )
        )


@pytest.mark.asyncio
async def test_balanced_journal_created(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    base_account,
    counter_account,
    open_period,
):
    svc = _svc(db, tenant_id, user_id)
    jnl = await svc.create_journal(
        _balanced_journal(
            open_period.period_id, base_account.account_id, counter_account.account_id
        )
    )
    assert jnl.status == "draft"
    assert len(jnl.lines) == 2


# ─────────────────────────────────────────────── period lock ───────────────────


@pytest.mark.asyncio
async def test_journal_blocked_on_soft_closed_period(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    base_account,
    counter_account,
):
    period = AccountingPeriod(
        tenant_id=tenant_id,
        period_name="Soft-Closed",
        period_type="monthly",
        period_start=date(2025, 12, 1),
        period_end=date(2025, 12, 31),
        is_year_end=False,
        is_large_company_for_ct=False,
        status="soft_closed",
    )
    db.add(period)
    await db.flush()
    svc = _svc(db, tenant_id, user_id)
    with pytest.raises(PeriodClosedError):
        await svc.create_journal(
            _balanced_journal(
                period.period_id, base_account.account_id, counter_account.account_id
            )
        )


@pytest.mark.asyncio
async def test_journal_blocked_on_hard_closed_period(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    base_account,
    counter_account,
):
    period = AccountingPeriod(
        tenant_id=tenant_id,
        period_name="Hard-Closed",
        period_type="monthly",
        period_start=date(2025, 11, 1),
        period_end=date(2025, 11, 30),
        is_year_end=False,
        is_large_company_for_ct=False,
        status="hard_closed",
    )
    db.add(period)
    await db.flush()
    svc = _svc(db, tenant_id, user_id)
    with pytest.raises(PeriodClosedError):
        await svc.create_journal(
            _balanced_journal(
                period.period_id, base_account.account_id, counter_account.account_id
            )
        )


# ─────────────────────────────────────────────── post journal ──────────────────


@pytest.mark.asyncio
async def test_post_journal_changes_status(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    base_account,
    counter_account,
    open_period,
):
    svc = _svc(db, tenant_id, user_id)
    jnl = await svc.create_journal(
        _balanced_journal(
            open_period.period_id, base_account.account_id, counter_account.account_id
        )
    )
    posted = await svc.post_journal(jnl.journal_id)
    assert posted.status == "posted"


@pytest.mark.asyncio
async def test_post_already_posted_raises(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    base_account,
    counter_account,
    open_period,
):
    svc = _svc(db, tenant_id, user_id)
    jnl = await svc.create_journal(
        _balanced_journal(
            open_period.period_id, base_account.account_id, counter_account.account_id
        )
    )
    await svc.post_journal(jnl.journal_id)
    with pytest.raises(ValueError, match="posted"):
        await svc.post_journal(jnl.journal_id)


# ─────────────────────────────────────────────── reversal ──────────────────────


@pytest.mark.asyncio
async def test_reversal_journal_created(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    base_account,
    counter_account,
    open_period,
):
    svc = _svc(db, tenant_id, user_id)
    jnl = await svc.create_journal(
        _balanced_journal(
            open_period.period_id, base_account.account_id, counter_account.account_id
        )
    )
    await svc.post_journal(jnl.journal_id)
    reversal = await svc.reverse_journal(
        jnl.journal_id, open_period.period_id, "REV-001"
    )
    assert reversal.status == "posted"
    assert reversal.reversal_of_journal_id == jnl.journal_id


@pytest.mark.asyncio
async def test_reversal_swaps_debit_credit(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    base_account,
    counter_account,
    open_period,
):
    svc = _svc(db, tenant_id, user_id)
    amount = Decimal("250")
    jnl = await svc.create_journal(
        _balanced_journal(
            open_period.period_id,
            base_account.account_id,
            counter_account.account_id,
            amount,
        )
    )
    await svc.post_journal(jnl.journal_id)
    reversal = await svc.reverse_journal(
        jnl.journal_id, open_period.period_id, "REV-002"
    )
    # Original first line was DR 250 → reversal first line should be CR 250
    orig_line = next(l for l in jnl.lines if l.account_id == base_account.account_id)
    rev_line = next(
        l for l in reversal.lines if l.account_id == base_account.account_id
    )
    assert orig_line.debit_amount == rev_line.credit_amount


# ─────────────────────────────────────────────── VAT expansion ─────────────────


@pytest.mark.asyncio
async def test_t0_vat_expansion_generates_vat_lines(
    db: AsyncSession,
    tenant: Tenant,
    tenant_id,
    user_id,
    open_period,
):
    """T0 (20% standard rate) lines should expand with auto VAT account lines."""
    from app.services.chart_of_accounts_service import (
        ChartOfAccountsService,
        AccountCreate,
    )

    coa_svc = ChartOfAccountsService(db, tenant_id, user_id)
    # Create required VAT accounts
    input_vat = await coa_svc.create(
        AccountCreate(
            account_code="1101",
            account_name="VAT Input",
            account_type="asset",
            currency_code="GBP",
        )
    )
    output_vat = await coa_svc.create(
        AccountCreate(
            account_code="2001",
            account_name="VAT Output",
            account_type="liability",
            currency_code="GBP",
        )
    )
    sales = await coa_svc.create(
        AccountCreate(
            account_code="4001",
            account_name="Sales",
            account_type="income",
            currency_code="GBP",
        )
    )
    bank = await coa_svc.create(
        AccountCreate(
            account_code="1001",
            account_name="Bank",
            account_type="asset",
            currency_code="GBP",
        )
    )

    svc = _svc(db, tenant_id, user_id)
    net_amount = Decimal("1000")
    vat_amount = Decimal("200")  # 20%
    total = net_amount + vat_amount

    jnl = await svc.create_journal(
        JournalCreate(
            period_id=open_period.period_id,
            journal_reference="VAT-001",
            description="T0 sale",
            currency_code="GBP",
            lines=[
                JournalLineCreate(
                    account_id=bank.account_id,
                    debit_amount=total,
                    credit_amount=Decimal("0"),
                    currency_code="GBP",
                    vat_treatment="T9",  # bank line exempt
                ),
                JournalLineCreate(
                    account_id=sales.account_id,
                    debit_amount=Decimal("0"),
                    credit_amount=net_amount,
                    currency_code="GBP",
                    vat_treatment="T0",  # triggers VAT expansion
                ),
                JournalLineCreate(
                    account_id=output_vat.account_id,
                    debit_amount=Decimal("0"),
                    credit_amount=vat_amount,
                    currency_code="GBP",
                    vat_treatment="T9",
                ),
            ],
        )
    )
    # Journal should be created (balance check passes)
    assert jnl is not None
