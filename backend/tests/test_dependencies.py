"""Tests for core/dependencies.py — get_current_user dependency.

Verifies JWT extraction, claim validation, and 401 rejection paths
by calling the dependency function directly (no live DB required).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.config import settings
from app.core.dependencies import CurrentUser, get_current_user


# ──────────────────────────────────── Helpers ─────────────────────────────────

_USER_ID = uuid.uuid4()
_TENANT_ID = uuid.uuid4()


def _make_token(
    *,
    user_id: uuid.UUID = _USER_ID,
    tenant_id: uuid.UUID = _TENANT_ID,
    roles: list[str] | None = None,
    token_type: str = "access",
    secret: str | None = None,
    algorithm: str | None = None,
    exp_delta: timedelta = timedelta(minutes=30),
) -> str:
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "roles": roles or ["viewer"],
        "type": token_type,
        "exp": datetime.now(timezone.utc) + exp_delta,
    }
    return jwt.encode(
        payload,
        secret or settings.JWT_SECRET_KEY,
        algorithm=algorithm or settings.JWT_ALGORITHM,
    )


# ──────────────────────────────────── Happy-path ──────────────────────────────


@pytest.mark.asyncio
async def test_valid_token_returns_current_user() -> None:
    token = _make_token(roles=["admin", "viewer"])
    user = await get_current_user(authorization=f"Bearer {token}")

    assert isinstance(user, CurrentUser)
    assert user.user_id == _USER_ID
    assert user.tenant_id == _TENANT_ID
    assert set(user.roles) == {"admin", "viewer"}


@pytest.mark.asyncio
async def test_valid_token_default_roles() -> None:
    """A token with no roles claim should produce an empty roles list."""
    payload = {
        "sub": str(_USER_ID),
        "tenant_id": str(_TENANT_ID),
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
        # intentionally omitting "roles"
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    user = await get_current_user(authorization=f"Bearer {token}")
    assert user.roles == []


# ──────────────────────────────────── 401 rejection paths ─────────────────────


@pytest.mark.asyncio
async def test_missing_authorization_header_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_non_bearer_scheme_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization="Basic dXNlcjpwYXNz")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_tampered_signature_raises_401() -> None:
    token = _make_token()
    tampered = token[:-4] + "XXXX"
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=f"Bearer {tampered}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_secret_raises_401() -> None:
    token = _make_token(secret="completely-different-secret-key!!")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_type_raises_401() -> None:
    """A 'refresh' token must not be accepted by get_current_user."""
    token = _make_token(token_type="refresh")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_sub_raises_401() -> None:
    payload = {
        "tenant_id": str(_TENANT_ID),
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_tenant_id_raises_401() -> None:
    payload = {
        "sub": str(_USER_ID),
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_raises_401() -> None:
    token = _make_token(exp_delta=timedelta(seconds=-1))
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=f"Bearer {token}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_401_includes_www_authenticate_header() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(authorization=None)
    assert exc_info.value.headers is not None
    assert "WWW-Authenticate" in exc_info.value.headers
    assert exc_info.value.headers["WWW-Authenticate"] == "Bearer"
