#!/usr/bin/env python3
"""create_tenant.py — CLI onboarding script for new KuberaTreasury customers.

Run from the repo root (with the .env file present, or DATABASE_URL exported):

    python scripts/create_tenant.py

The script will interactively prompt for all required fields and then:
  1. Create a Tenant record
  2. Create the first system_admin user for that tenant
  3. Seed the UK standard chart of accounts (HMRC nominal codes + VAT treatment)
  4. Write a default tax profile (HMRC obligation schedule)
  5. Print a summary with tenant_id, admin user_id, and completion message
"""
from __future__ import annotations

import asyncio
import getpass
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Make the backend app package importable ───────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _load_backend_env_defaults() -> None:
    def _is_placeholder_db_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        host = (parsed.hostname or "").strip().lower()
        return host in {"", "host", "your-host", "db", "database"}

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
        if not key:
            continue

        if key not in os.environ:
            os.environ[key] = value
            continue

        if key == "DATABASE_URL" and _is_placeholder_db_url(os.environ[key]):
            os.environ[key] = value


_load_backend_env_defaults()

import bcrypt  # noqa: E402  — imported after sys.path patch
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import _get_session_factory  # noqa: E402
from app.models import Role, Tenant, User, UserRole  # noqa: E402
from app.services.chart_of_accounts_service import (  # noqa: E402
    ChartOfAccountsService,
)

# ─────────────────────────────────────────────────── helpers ──────────────────


def _hash_password(password: str) -> str:
    """Hash *password* with bcrypt using the configured round count."""
    rounds = min(max(settings.BCRYPT_ROUNDS, 4), 31)
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)
    ).decode("utf-8")


def _validate_password_policy(password: str) -> None:
    """Enforce the same password policy as AuthService (12+ chars, complexity)."""
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters.")
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    if not all([has_upper, has_lower, has_digit, has_special]):
        raise ValueError(
            "Password must include uppercase, lowercase, digit, and special character."
        )


def _prompt(
    label: str,
    *,
    default: str | None = None,
    required: bool = True,
    secret: bool = False,
) -> str:
    """Prompt the user for input with an optional default value."""
    suffix = f" [{default}]" if default is not None else ""
    display = f"  {label}{suffix}: "

    while True:
        try:
            value = getpass.getpass(display) if secret else input(display).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)

        if not value:
            if default is not None:
                return default
            if not required:
                return ""
            print("    ✗  This field is required — please enter a value.")
            continue
        return value


def _prompt_optional(label: str) -> str | None:
    """Prompt for an optional field; return None if the user presses Enter."""
    value = _prompt(label, default="", required=False)
    return value or None


def _describe_database_target() -> str:
    """Return a redacted human-readable DB target for pre-flight logging."""
    parsed = urlparse(settings.DATABASE_URL)
    host = parsed.hostname or "<unknown-host>"
    port = parsed.port or "<default>"
    db_name = (parsed.path or "/").lstrip("/") or "<default-db>"
    scheme = parsed.scheme or "<unknown-driver>"
    user = parsed.username or "<unknown-user>"
    return f"{scheme}://{user}:***@{host}:{port}/{db_name}"


def _validate_database_target() -> None:
    parsed = urlparse(settings.DATABASE_URL)
    host = (parsed.hostname or "").strip().lower()
    if host in {"", "host", "your-host", "db", "database"}:
        raise RuntimeError(
            "DATABASE_URL appears to use a placeholder host. "
            "Set DATABASE_URL to your real local DB (e.g. "
            "postgresql+psycopg://kubera:kubera_local@localhost:55432/kubera_dev) "
            "or ensure backend/.env has the correct value."
        )


# ─────────────────────────────────────────────────── input collection ─────────


def _collect_inputs() -> dict:
    """Interactively gather all data needed to onboard a tenant."""
    print("\n" + "═" * 56)
    print("  KuberaTreasury — New Tenant Onboarding")
    print("═" * 56)

    # ── Company details ────────────────────────────────────────────────────────
    print("\n── Company details ───────────────────────────────────")
    company_name = _prompt("Company name")

    company_number_raw = _prompt_optional(
        "Companies House registration number (optional — press Enter to skip)"
    )

    vrn_raw = _prompt_optional(
        "VAT registration number — 9 digits, no 'GB' prefix (optional — press Enter to skip)"
    )
    if vrn_raw:
        # Strip common 'GB' prefix and whitespace before validating
        vrn_normalised = vrn_raw.strip().upper().removeprefix("GB").replace(" ", "")
        if len(vrn_normalised) != 9 or not vrn_normalised.isdigit():
            print(
                f"    ✗  VRN must be exactly 9 digits (got '{vrn_normalised}'). "
                "Clearing — you can update it later via the API."
            )
            vrn_normalised = None
    else:
        vrn_normalised = None

    base_currency = _prompt("Base currency", default="GBP").upper()
    if len(base_currency) != 3:
        print("    ✗  Currency code must be 3 characters; defaulting to GBP.")
        base_currency = "GBP"

    # ── Admin user ─────────────────────────────────────────────────────────────
    print("\n── First system_admin user ───────────────────────────")
    admin_email = _prompt("Admin email address")

    admin_password: str = ""
    while True:
        admin_password = _prompt("Admin password (input hidden)", secret=True)
        confirm = _prompt("Confirm password   (input hidden)", secret=True)
        if admin_password != confirm:
            print("    ✗  Passwords do not match — try again.")
            continue
        try:
            _validate_password_policy(admin_password)
            break
        except ValueError as exc:
            print(f"    ✗  {exc}")

    # ── HMRC obligation schedule ───────────────────────────────────────────────
    print("\n── HMRC obligation schedule ──────────────────────────")

    vat_stagger_raw = _prompt_optional(
        "VAT stagger group (A1 / A2 / A3 — optional, press Enter to skip)"
    )
    vat_stagger: str | None = None
    if vat_stagger_raw:
        vat_stagger_upper = vat_stagger_raw.strip().upper()
        if vat_stagger_upper in ("A1", "A2", "A3"):
            vat_stagger = vat_stagger_upper
        else:
            print(
                f"    ✗  '{vat_stagger_raw}' is not a valid stagger group (A1/A2/A3). "
                "Skipping — update later via tax profile API."
            )

    large_ct_raw = _prompt(
        "Is this a large company for CT quarterly instalments? (y/N)", default="n"
    ).lower()
    large_company_ct = large_ct_raw in ("y", "yes")

    return {
        "company_name": company_name,
        "company_number": company_number_raw,
        "vrn": vrn_normalised,
        "base_currency": base_currency,
        "admin_email": admin_email,
        "admin_password": admin_password,
        "vat_stagger": vat_stagger,
        "large_company_ct": large_company_ct,
    }


# ─────────────────────────────────────────────────── database work ────────────


async def _run_onboarding(
    *,
    company_name: str,
    company_number: str | None,
    vrn: str | None,
    base_currency: str,
    admin_email: str,
    admin_password: str,
    vat_stagger: str | None,
    large_company_ct: bool,
) -> dict:
    """Persist all onboarding artefacts inside a single transaction."""
    factory = _get_session_factory()
    async with factory() as db:
        db: AsyncSession

        # ── Step 1: Tenant record ──────────────────────────────────────────────
        tenant = Tenant(
            tenant_id=uuid.uuid4(),
            tenant_name=company_name,
            company_number=company_number or None,
            vrn=vrn or None,
            base_currency=base_currency,
            classification_level="OFFICIAL",
            is_active=True,
        )
        db.add(tenant)
        await db.flush()  # assign tenant_id into the session identity map
        tenant_id: uuid.UUID = tenant.tenant_id
        print(f"    ✔  Tenant created          ({tenant_id})")

        # ── Step 2: system_admin Role + User ──────────────────────────────────
        admin_role = Role(
            tenant_id=tenant_id,
            role_name="system_admin",
            description="System administrator — full tenant access",
        )
        db.add(admin_role)
        await db.flush()

        password_hash = _hash_password(admin_password)
        admin_user = User(
            tenant_id=tenant_id,
            username=admin_email,       # username stores the email address
            password_hash=password_hash,
            is_active=True,
        )
        db.add(admin_user)
        await db.flush()
        user_id: uuid.UUID = admin_user.user_id

        db.add(
            UserRole(
                tenant_id=tenant_id,
                user_id=user_id,
                role_id=admin_role.role_id,
            )
        )
        await db.flush()
        print(f"    ✔  Admin user created       ({user_id})")

        # ── Step 3: UK standard chart of accounts ──────────────────────────────
        coa_svc = ChartOfAccountsService(db, tenant_id, user_id)
        seeded = await coa_svc.seed_uk_standard()
        print(f"    ✔  Chart of accounts seeded ({len(seeded)} accounts)")

        # ── Step 4: Default HMRC tax profile (obligation schedule) ─────────────
        ct_due_rule = (
            "quarterly_instalments" if large_company_ct else "9_months_post_year_end"
        )
        await db.execute(
            text(
                """
                INSERT INTO tax_profiles (
                    tax_profile_id,
                    tenant_id,
                    is_large_company_for_ct,
                    ct_due_rule,
                    cir_threshold_amount,
                    vat_stagger,
                    updated_at
                ) VALUES (
                    :id,
                    :tenant_id,
                    :large_co,
                    :ct_rule,
                    :cir_threshold,
                    :vat_stagger,
                    now()
                )
                ON CONFLICT ON CONSTRAINT uq_tax_profile_tenant DO NOTHING
                """
            ),
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "large_co": large_company_ct,
                "ct_rule": ct_due_rule,
                "cir_threshold": "2000000.00",
                "vat_stagger": vat_stagger,
            },
        )
        print(
            f"    ✔  Tax profile set           "
            f"(CT rule: {ct_due_rule}, VAT stagger: {vat_stagger or 'not set'})"
        )

        await db.commit()

        return {
            "tenant_id": tenant_id,
            "admin_user_id": user_id,
            "accounts_seeded": len(seeded),
            "company_name": company_name,
        }


# ─────────────────────────────────────────────────── entry point ─────────────


def main() -> None:
    print("\n── Database target ───────────────────────────────────")
    print(f"  { _describe_database_target() }")

    try:
        _validate_database_target()
    except RuntimeError as exc:
        print(f"\n  ✗  {exc}")
        sys.exit(1)

    inputs = _collect_inputs()

    print("\n── Creating records ──────────────────────────────────")
    try:
        result = asyncio.run(_run_onboarding(**inputs))
    except Exception as exc:  # noqa: BLE001
        print(f"\n  ✗  Onboarding failed: {exc}")
        sys.exit(1)

    print("\n" + "═" * 56)
    print("  Run complete — tenant ready")
    print("═" * 56)
    print(f"  Company      : {result['company_name']}")
    print(f"  Tenant ID    : {result['tenant_id']}")
    print(f"  Admin user ID: {result['admin_user_id']}")
    print(f"  CoA accounts : {result['accounts_seeded']} seeded")
    print("═" * 56 + "\n")


if __name__ == "__main__":
    main()
