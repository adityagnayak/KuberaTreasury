"""Tests for GDPR / UK-GDPR right-to-erasure (PII erasure) functionality.

Covers:
- Successful erasure nulls all PII fields and sets is_erased=True.
- Financial ledger records (journals) for the user survive erasure intact.
- erased_at timestamp is populated on the PersonalDataRecord row.
- A caller without the system_admin role receives HTTP 403.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.main import create_app
from app.models import (
    AccountingPeriod,
    Journal,
    PersonalDataRecord,
    Tenant,
)
from app.services.auth_service import AuthService


# ─────────────────────────────────────────────────── helpers ──────────────────


async def _make_personal_data_record(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    full_name: str = "Jane Smith",
    email: str = "jane@example.com",
    phone: str = "+44 7700 900000",
    address: str = "1 Treasury Lane, London, EC1A 1BB",
) -> PersonalDataRecord:
    record = PersonalDataRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        full_name=full_name,
        email=email,
        phone=phone,
        address=address,
    )
    db.add(record)
    await db.flush()
    return record


# ═════════════════════════════════════════════════════════════════════════════
# 1. Erasure nulls all PII fields
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_erasure_nulls_pii_fields(db: AsyncSession, tenant: Tenant) -> None:
    """After erasure, all PII columns must be NULL and is_erased must be True."""
    target_user_id = uuid.uuid4()

    await _make_personal_data_record(
        db, tenant_id=tenant.tenant_id, user_id=target_user_id
    )

    svc = AuthService()
    result = await svc.erase_personal_data(
        db,
        tenant.tenant_id,
        target_user_id,
        requested_by=uuid.uuid4(),
    )
    await db.flush()

    # Verify service response
    assert result.erased is True
    assert result.user_id == target_user_id
    assert result.erased_at is not None

    # Verify the model row — fetch fresh to confirm DB state
    row = (
        (
            await db.execute(
                select(PersonalDataRecord).where(
                    PersonalDataRecord.user_id == target_user_id
                )
            )
        )
        .scalars()
        .one()
    )

    assert row.full_name is None, "full_name must be nulled after erasure"
    assert row.email is None, "email must be nulled after erasure"
    assert row.phone is None, "phone must be nulled after erasure"
    assert row.address is None, "address must be nulled after erasure"
    assert row.is_erased is True
    # The row itself must NOT be deleted — erasure is a soft operation
    assert row.id is not None


# ═════════════════════════════════════════════════════════════════════════════
# 2. Financial ledger records survive erasure
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ledger_records_survive_erasure(
    db: AsyncSession, tenant: Tenant, open_period: AccountingPeriod
) -> None:
    """Journals (and all other ledger rows) must be untouched by PII erasure."""
    target_user_id = uuid.uuid4()

    # Create a journal referencing the user (e.g. as poster)
    journal = Journal(
        tenant_id=tenant.tenant_id,
        period_id=open_period.period_id,
        journal_reference="JNL-GDPR-001",
        description="Journal to verify ledger survival",
        journal_type="manual",
        status="draft",
        currency_code="GBP",
        posted_by_user_id=target_user_id,
    )
    db.add(journal)

    await _make_personal_data_record(
        db, tenant_id=tenant.tenant_id, user_id=target_user_id
    )

    await db.flush()
    journal_id = journal.journal_id

    # Erase PII
    svc = AuthService()
    await svc.erase_personal_data(
        db,
        tenant.tenant_id,
        target_user_id,
        requested_by=uuid.uuid4(),
    )
    await db.flush()

    # The journal row must still exist and be unchanged
    surviving_journal = (
        (
            await db.execute(
                select(Journal).where(Journal.journal_id == journal_id)
            )
        )
        .scalars()
        .one_or_none()
    )

    assert surviving_journal is not None, "Journal must not be deleted by PII erasure"
    assert surviving_journal.journal_reference == "JNL-GDPR-001"
    assert surviving_journal.posted_by_user_id == target_user_id


# ═════════════════════════════════════════════════════════════════════════════
# 3. erased_at timestamp is populated
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_erased_at_is_set(db: AsyncSession, tenant: Tenant) -> None:
    """erased_at must be a non-null timezone-aware datetime after erasure."""
    target_user_id = uuid.uuid4()

    await _make_personal_data_record(
        db, tenant_id=tenant.tenant_id, user_id=target_user_id
    )

    svc = AuthService()
    result = await svc.erase_personal_data(
        db,
        tenant.tenant_id,
        target_user_id,
        requested_by=uuid.uuid4(),
    )
    await db.flush()

    # Service response carries the erasure timestamp
    assert result.erased_at is not None

    # Row in DB also has erased_at set
    row = (
        (
            await db.execute(
                select(PersonalDataRecord).where(
                    PersonalDataRecord.user_id == target_user_id
                )
            )
        )
        .scalars()
        .one()
    )
    assert row.erased_at is not None
    assert row.is_erased is True


# ═════════════════════════════════════════════════════════════════════════════
# 4. Non-system_admin caller receives HTTP 403
# ═════════════════════════════════════════════════════════════════════════════


def test_non_system_admin_gets_403() -> None:
    """Any role other than system_admin must be rejected with HTTP 403."""
    app = create_app()

    non_admin = CurrentUser(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        roles=["auditor"],  # NOT system_admin
    )

    # Override auth so no real JWT is needed
    app.dependency_overrides[get_current_user] = lambda: non_admin

    # Override DB so no PostgreSQL connection is attempted
    async def _mock_db():
        yield AsyncMock(spec=AsyncSession)

    app.dependency_overrides[get_db] = _mock_db

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.delete(f"/api/v1/users/{uuid.uuid4()}/personal-data")
        assert response.status_code == 403
        body = response.json()
        assert "system_admin" in body.get("detail", "").lower() or body.get("detail") == "Forbidden: system_admin role required"
    finally:
        app.dependency_overrides.clear()
