#!/usr/bin/env python3
"""Generate current TOTP code for an admin user in local/demo environments.

Usage (from repo root):
  K:/KuberaTreasury/.venv/Scripts/python.exe scripts/generate_admin_totp.py \
      --tenant-id <tenant_uuid> \
      --email admin@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

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
from sqlalchemy import select  # noqa: E402

from app.core.database import _get_session_factory  # noqa: E402
from app.models import AuthFactor, User  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate current TOTP for an admin.")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID")
    parser.add_argument("--email", required=True, help="Admin email/username")
    return parser.parse_args()


async def _run(tenant_id: uuid.UUID, email: str) -> None:
    session_factory = _get_session_factory()

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

        factor = (
            await db.execute(
                select(AuthFactor).where(
                    AuthFactor.tenant_id == tenant_id,
                    AuthFactor.user_id == user.user_id,
                    AuthFactor.factor_type == "totp",
                    AuthFactor.is_enabled.is_(True),
                )
            )
        ).scalar_one_or_none()
        if factor is None or not factor.totp_secret_encrypted:
            raise ValueError("Enabled TOTP factor not found. Run bootstrap_admin_login.py first.")

        totp = pyotp.TOTP(factor.totp_secret_encrypted)
        code = totp.now()

    seconds_remaining = 30 - (int(time.time()) % 30)

    print("\n════════════════════════════════════════════════════════")
    print("  Current TOTP code")
    print("════════════════════════════════════════════════════════")
    print(f"  Tenant ID : {tenant_id}")
    print(f"  Email     : {email}")
    print(f"  TOTP code : {code}")
    print(f"  Expires in: {seconds_remaining}s")
    print("════════════════════════════════════════════════════════\n")


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(_run(uuid.UUID(args.tenant_id.strip()), args.email.strip()))
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
