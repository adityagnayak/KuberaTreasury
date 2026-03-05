#!/usr/bin/env python3
"""Bootstrap admin login credentials for local/demo environments.

This one-time utility does three things for an existing tenant admin user:
1. Resets password to a known value
2. Clears recent login-attempt lockouts for that user
3. Bootstraps and enables TOTP MFA, printing a current code + backup codes

Usage (from repo root):
    K:/KuberaTreasury/.venv/Scripts/python.exe scripts/bootstrap_admin_login.py \
        --tenant-id <tenant_uuid> \
        --email admin@example.com \
        --password 'DemoPassw0rd!'
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _load_backend_env_defaults() -> None:
    env_path = _BACKEND_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.split("#", 1)[0].strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_backend_env_defaults()

import pyotp  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.core.database import _get_session_factory  # noqa: E402
from app.models import AuthFactor, LoginAttempt, User  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap admin login + MFA.")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID")
    parser.add_argument("--email", required=True, help="Admin email/username")
    parser.add_argument("--password", required=True, help="New admin password")
    return parser.parse_args()


def _password_policy_check(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    checks = [
        any(ch.isupper() for ch in password),
        any(ch.islower() for ch in password),
        any(ch.isdigit() for ch in password),
        any(not ch.isalnum() for ch in password),
    ]
    if not all(checks):
        raise ValueError(
            "Password must include uppercase, lowercase, digit, and special character"
        )


def _extract_totp_secret(otpauth_uri: str) -> str:
    query = parse_qs(urlparse(otpauth_uri).query)
    secret = query.get("secret", [""])[0]
    if not secret:
        raise ValueError("Could not extract TOTP secret from otpauth URI")
    return secret


async def _run(tenant_id: uuid.UUID, email: str, password: str) -> None:
    _password_policy_check(password)

    session_factory = _get_session_factory()
    svc = AuthService()

    async with session_factory() as db:
        user = (
            await db.execute(
                select(User).where(
                    User.tenant_id == tenant_id,
                    User.username == email,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise ValueError("Active user not found for tenant/email")

        user.password_hash = svc._hash_password(password)

        await db.execute(
            delete(LoginAttempt).where(
                LoginAttempt.tenant_id == tenant_id,
                LoginAttempt.username == email,
            )
        )

        mfa = await svc.setup_mfa(db, tenant_id, user.user_id, user.username)
        factor = (
            await db.execute(
                select(AuthFactor).where(
                    AuthFactor.tenant_id == tenant_id,
                    AuthFactor.user_id == user.user_id,
                    AuthFactor.factor_type == "totp",
                )
            )
        ).scalar_one()
        factor.is_enabled = True

        await db.commit()

    secret = _extract_totp_secret(mfa.otpauth_uri)
    current_totp = pyotp.TOTP(secret).now()

    print("\n════════════════════════════════════════════════════════")
    print("  Admin login bootstrap complete")
    print("════════════════════════════════════════════════════════")
    print(f"  Tenant ID : {tenant_id}")
    print(f"  Email     : {email}")
    print(f"  Password  : {password}")
    print(f"  TOTP code : {current_totp}  (time-based, refreshes every 30s)")
    print("  Backup codes:")
    for code in mfa.backup_codes:
        print(f"    - {code}")
    print("════════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(
            _run(
                tenant_id=uuid.UUID(args.tenant_id.strip()),
                email=args.email.strip(),
                password=args.password,
            )
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
