from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    IpAllowlistEntry,
    MfaBackupCode,
    PersonalDataRecord,
    TenantSecuritySetting,
    User,
)
from app.services.auth_service import AuthService, ChangePasswordRequest, LoginRequest


@pytest.mark.asyncio
async def test_login_success_creates_session(db, tenant):
    svc = AuthService()
    user = User(
        tenant_id=tenant.tenant_id,
        username="cfo@example.com",
        password_hash=svc._hash_password("Passw0rd!Strong"),
    )
    db.add(user)
    await db.flush()

    token, refresh, meta = await svc.login(
        db,
        LoginRequest(tenant_id=tenant.tenant_id, email="cfo@example.com", password="Passw0rd!Strong"),
        "127.0.0.1",
        "pytest",
    )
    await db.flush()

    assert token.access_token
    assert refresh
    assert meta["tenant_id"] == str(tenant.tenant_id)


@pytest.mark.asyncio
async def test_password_change_rejects_weak(db, tenant):
    svc = AuthService()
    user = User(
        tenant_id=tenant.tenant_id,
        username="user@example.com",
        password_hash=svc._hash_password("Passw0rd!Strong"),
    )
    db.add(user)
    await db.flush()

    with pytest.raises(ValueError):
        await svc.change_password(
            db,
            tenant.tenant_id,
            user.user_id,
            ChangePasswordRequest(current_password="Passw0rd!Strong", new_password="weakpass"),
        )


@pytest.mark.asyncio
async def test_mfa_setup_generates_backup_codes(db, tenant):
    svc = AuthService()
    user = User(
        tenant_id=tenant.tenant_id,
        username="ops@example.com",
        password_hash=svc._hash_password("Passw0rd!Strong"),
    )
    db.add(user)
    await db.flush()

    setup = await svc.setup_mfa(db, tenant.tenant_id, user.user_id, user.username)
    await db.flush()

    rows = (await db.execute(select(MfaBackupCode).where(MfaBackupCode.user_id == user.user_id))).scalars().all()
    assert setup.otpauth_uri.startswith("otpauth://")
    assert len(setup.backup_codes) == 10
    assert len(rows) == 10


@pytest.mark.asyncio
async def test_personal_data_erasure(db, tenant):
    user_id = uuid.uuid4()
    db.add(
        PersonalDataRecord(
            tenant_id=tenant.tenant_id,
            subject_type=f"user:{user_id}",
            full_name="A User",
            email="a@example.com",
        )
    )
    await db.flush()

    svc = AuthService()
    result = await svc.erase_personal_data(db, tenant.tenant_id, user_id, uuid.uuid4())
    await db.flush()

    assert result.anonymised_count == 1


@pytest.mark.asyncio
async def test_ip_allowlist_enforced(db, tenant):
    db.add(TenantSecuritySetting(tenant_id=tenant.tenant_id, ip_allowlist_enforced=True))
    db.add(IpAllowlistEntry(tenant_id=tenant.tenant_id, cidr="10.10.0.0/16"))
    await db.flush()

    svc = AuthService()
    assert await svc.is_ip_allowed(db, tenant.tenant_id, "10.10.10.10") is True
    assert await svc.is_ip_allowed(db, tenant.tenant_id, "192.168.1.1") is False
