"""Tests for app.models.users — PersonalDataRecord ORM model.

Verifies schema constraints, default values, the AES-256-GCM transparent
encryption of PII fields, and the soft-erasure state transition.
All tests use the in-memory SQLite DB provided by conftest.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import PersonalDataRecord


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


async def _create_record(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    **kwargs,
) -> PersonalDataRecord:
    record = PersonalDataRecord(
        tenant_id=tenant_id,
        user_id=user_id or uuid.uuid4(),
        **kwargs,
    )
    db.add(record)
    await db.flush()
    return record


# ═════════════════════════════════════════════════════════════════════════════
# Creation & defaults
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_created_with_all_pii_fields(db: AsyncSession, tenant) -> None:
    record = await _create_record(
        db,
        tenant.tenant_id,
        full_name="Jane Smith",
        email="jane@example.com",
        phone="+44 7700 900000",
        address="1 Treasury Lane, London, EC1A 1BB",
    )
    assert record.full_name == "Jane Smith"
    assert record.email == "jane@example.com"
    assert record.phone == "+44 7700 900000"
    assert record.address == "1 Treasury Lane, London, EC1A 1BB"


@pytest.mark.asyncio
async def test_pii_fields_default_to_none(db: AsyncSession, tenant) -> None:
    record = await _create_record(db, tenant.tenant_id)
    assert record.full_name is None
    assert record.email is None
    assert record.phone is None
    assert record.address is None


@pytest.mark.asyncio
async def test_is_erased_defaults_to_false(db: AsyncSession, tenant) -> None:
    record = await _create_record(db, tenant.tenant_id)
    assert record.is_erased is False


@pytest.mark.asyncio
async def test_erased_at_defaults_to_none(db: AsyncSession, tenant) -> None:
    record = await _create_record(db, tenant.tenant_id)
    assert record.erased_at is None


@pytest.mark.asyncio
async def test_id_is_auto_generated_uuid(db: AsyncSession, tenant) -> None:
    record = await _create_record(db, tenant.tenant_id)
    assert isinstance(record.id, uuid.UUID)


# ═════════════════════════════════════════════════════════════════════════════
# Encryption at rest
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pii_stored_encrypted_not_as_plaintext(
    db: AsyncSession, tenant
) -> None:
    """Verify the raw stored value is NOT the plaintext (it is AES-GCM ciphertext)."""
    target_user_id = uuid.uuid4()
    await _create_record(
        db,
        tenant.tenant_id,
        user_id=target_user_id,
        full_name="Secret Name",
        email="secret@example.com",
    )
    await db.flush()

    # Query the raw column value directly via SQL — bypasses the TypeDecorator.
    # SQLite stores UUID(as_uuid=True) as 32-char hex without hyphens.
    row = await db.execute(
        text(
            "SELECT full_name, email FROM personal_data_records "
            "WHERE user_id = :uid"
        ),
        {"uid": target_user_id.hex},
    )
    raw_full_name, raw_email = row.one()

    assert raw_full_name is not None
    assert raw_email is not None
    assert raw_full_name != "Secret Name", "Plaintext must not be stored on disk"
    assert raw_email != "secret@example.com", "Plaintext must not be stored on disk"


@pytest.mark.asyncio
async def test_pii_roundtrips_transparently(db: AsyncSession, tenant) -> None:
    """ORM layer must decrypt on read so the application sees plain text."""
    target_user_id = uuid.uuid4()
    await _create_record(
        db,
        tenant.tenant_id,
        user_id=target_user_id,
        full_name="Jane Smith",
        email="jane@example.com",
        phone="+44 7700 900000",
        address="1 Treasury Lane",
    )
    await db.flush()

    # Re-fetch via ORM to exercise process_result_value.
    result = (
        await db.execute(
            select(PersonalDataRecord).where(
                PersonalDataRecord.user_id == target_user_id
            )
        )
    ).scalars().one()

    assert result.full_name == "Jane Smith"
    assert result.email == "jane@example.com"
    assert result.phone == "+44 7700 900000"
    assert result.address == "1 Treasury Lane"


@pytest.mark.asyncio
async def test_two_records_with_same_pii_have_different_ciphertext(
    db: AsyncSession, tenant
) -> None:
    """Each encrypt call uses a fresh random nonce — same value, different blob."""
    uid1, uid2 = uuid.uuid4(), uuid.uuid4()
    await _create_record(
        db, tenant.tenant_id, user_id=uid1, email="shared@example.com"
    )
    await _create_record(
        db, tenant.tenant_id, user_id=uid2, email="shared@example.com"
    )
    await db.flush()

    row = await db.execute(
        text(
            "SELECT user_id, email FROM personal_data_records "
            "WHERE user_id IN (:u1, :u2)"
        ),
        {"u1": uid1.hex, "u2": uid2.hex},
    )
    rows = row.fetchall()
    assert len(rows) == 2
    raw_emails = {r[1] for r in rows}
    assert len(raw_emails) == 2, "Different nonces must produce different ciphertexts"


# ═════════════════════════════════════════════════════════════════════════════
# Uniqueness constraint — one PersonalDataRecord per user_id
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_duplicate_user_id_raises_integrity_error(
    db: AsyncSession, tenant
) -> None:
    """user_id has a UNIQUE constraint — a second insert for same user must fail."""
    shared_user_id = uuid.uuid4()
    await _create_record(db, tenant.tenant_id, user_id=shared_user_id)
    await db.flush()

    with pytest.raises((IntegrityError, Exception)):
        await _create_record(db, tenant.tenant_id, user_id=shared_user_id)
        await db.flush()


# ═════════════════════════════════════════════════════════════════════════════
# Soft erasure — state transitions
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_soft_erasure_nulls_pii_and_sets_flags(
    db: AsyncSession, tenant
) -> None:
    """Setting is_erased=True and nulling PII fields is the correct erasure pattern."""
    uid = uuid.uuid4()
    record = await _create_record(
        db,
        tenant.tenant_id,
        user_id=uid,
        full_name="Before Erasure",
        email="before@example.com",
        phone="01234 567890",
        address="Old Address",
    )
    await db.flush()

    # Perform erasure (the same logic as AuthService.erase_personal_data)
    now = datetime.now(timezone.utc)
    record.full_name = None
    record.email = None
    record.phone = None
    record.address = None
    record.is_erased = True
    record.erased_at = now
    db.add(record)
    await db.flush()

    # Re-fetch and verify
    refreshed = (
        await db.execute(
            select(PersonalDataRecord).where(PersonalDataRecord.user_id == uid)
        )
    ).scalars().one()

    assert refreshed.is_erased is True
    assert refreshed.erased_at is not None
    assert refreshed.full_name is None
    assert refreshed.email is None
    assert refreshed.phone is None
    assert refreshed.address is None
    # Row itself must NOT be deleted
    assert refreshed.id is not None
    assert refreshed.tenant_id == tenant.tenant_id


@pytest.mark.asyncio
async def test_row_survives_after_erasure(db: AsyncSession, tenant) -> None:
    """The PersonalDataRecord row must never be deleted — only its fields nulled."""
    uid = uuid.uuid4()
    record = await _create_record(
        db, tenant.tenant_id, user_id=uid, full_name="Persistent Row"
    )
    record_id = record.id
    await db.flush()

    record.full_name = None
    record.is_erased = True
    record.erased_at = datetime.now(timezone.utc)
    db.add(record)
    await db.flush()

    count_row = await db.execute(
        text("SELECT COUNT(*) FROM personal_data_records WHERE id = :pk"),
        {"pk": record_id.hex},
    )
    count = count_row.scalar()
    assert count == 1, "Erased row must remain in the database"


# ═════════════════════════════════════════════════════════════════════════════
# Table metadata
# ═════════════════════════════════════════════════════════════════════════════


def test_tablename_is_correct() -> None:
    assert PersonalDataRecord.__tablename__ == "personal_data_records"
