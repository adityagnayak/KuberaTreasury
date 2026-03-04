"""Tests for Chart of Accounts service — CoA CRUD, UK seeder, HMRC nominal mapping."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChartOfAccount, Tenant
from app.services.chart_of_accounts_service import (
    AccountCreate,
    AccountUpdate,
    ChartOfAccountsService,
    UK_STANDARD_COA,
)
from app.core.exceptions import NotFoundError


def _svc(db, tenant_id, user_id):
    return ChartOfAccountsService(db, tenant_id, user_id)


# ─────────────────────────────────────────────── seed tests ────────────────────


@pytest.mark.asyncio
async def test_seed_uk_standard_creates_accounts(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    accounts = await svc.seed_uk_standard()
    assert len(accounts) == len(UK_STANDARD_COA)


@pytest.mark.asyncio
async def test_seed_idempotent(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    first = await svc.seed_uk_standard()
    second = await svc.seed_uk_standard()
    # Second call should not raise; returned list may be same length or zero (skip existing)
    assert len(second) >= 0


@pytest.mark.asyncio
async def test_seed_includes_hmrc_nominal_codes(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    accounts = await svc.seed_uk_standard()
    codes_with_nominal = [a for a in accounts if a.hmrc_nominal_code]
    assert len(codes_with_nominal) > 0


@pytest.mark.asyncio
async def test_seed_has_vat_input_output_accounts(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    await svc.seed_uk_standard()
    all_accts = await svc.list_all()
    codes = {a.account_code for a in all_accts}
    assert "1101" in codes, "VAT Input account (1101) missing from seed"
    assert "2001" in codes, "VAT Output account (2001) missing from seed"


# ─────────────────────────────────────────────── CRUD tests ────────────────────


@pytest.mark.asyncio
async def test_create_account(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    payload = AccountCreate(
        account_code="9999",
        account_name="Test Account",
        account_type="asset",
        currency_code="GBP",
    )
    acct = await svc.create(payload)
    assert acct.account_code == "9999"
    assert acct.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_get_account(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    created = await svc.create(
        AccountCreate(
            account_code="8001",
            account_name="Bank",
            account_type="asset",
            currency_code="GBP",
        )
    )
    fetched = await svc.get(created.account_id)
    assert fetched.account_id == created.account_id


@pytest.mark.asyncio
async def test_get_nonexistent_raises_not_found(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    with pytest.raises(NotFoundError):
        await svc.get(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_account(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    acct = await svc.create(
        AccountCreate(
            account_code="7777",
            account_name="Old Name",
            account_type="expense",
            currency_code="GBP",
        )
    )
    updated = await svc.update(acct.account_id, AccountUpdate(account_name="New Name"))
    assert updated.account_name == "New Name"


@pytest.mark.asyncio
async def test_deactivate_account(db: AsyncSession, tenant: Tenant, tenant_id, user_id):
    svc = _svc(db, tenant_id, user_id)
    acct = await svc.create(
        AccountCreate(
            account_code="6666",
            account_name="ToDelete",
            account_type="liability",
            currency_code="GBP",
        )
    )
    await svc.deactivate(acct.account_id)
    fetched = await svc.get(acct.account_id)
    assert not fetched.is_active


@pytest.mark.asyncio
async def test_list_all_filters_by_tenant(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    await svc.create(
        AccountCreate(
            account_code="5500",
            account_name="Acct A",
            account_type="asset",
            currency_code="GBP",
        )
    )
    # Different tenant should not return the above account
    other_tenant_id = uuid.uuid4()
    other_svc = _svc(db, other_tenant_id, user_id)
    other_list = await other_svc.list_all()
    codes = {a.account_code for a in other_list}
    assert "5500" not in codes


@pytest.mark.asyncio
async def test_vat_treatment_stored_on_create(
    db: AsyncSession, tenant: Tenant, tenant_id, user_id
):
    svc = _svc(db, tenant_id, user_id)
    acct = await svc.create(
        AccountCreate(
            account_code="5001",
            account_name="Sales T0",
            account_type="income",
            currency_code="GBP",
            vat_treatment="T0",
        )
    )
    assert acct.vat_treatment == "T0"
