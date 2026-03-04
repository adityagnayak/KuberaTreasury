from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from sqlalchemy import create_engine, text


DEFAULT_POLICIES = [
    {
        "policy_name": "tier_lt_10k",
        "currency_code": "GBP",
        "threshold_amount": "10000.00",
        "required_approvals": 1,
    },
    {
        "policy_name": "tier_10k_100k",
        "currency_code": "GBP",
        "threshold_amount": "100000.00",
        "required_approvals": 1,
    },
    {
        "policy_name": "tier_100k_500k",
        "currency_code": "GBP",
        "threshold_amount": "500000.00",
        "required_approvals": 1,
    },
    {
        "policy_name": "tier_gt_500k",
        "currency_code": "GBP",
        "threshold_amount": "999999999.99",
        "required_approvals": 2,
    },
]

DEFAULT_SANCTIONS_ENTITIES = [
    "Bank Melli Iran",
    "Islamic Revolutionary Guard Corps",
    "National Iranian Oil Company",
    "Syrian Arab Airlines",
    "Belarusian State Security Committee",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap UAT Phase 4 data (approval matrix defaults and sanctions snapshot)."
    )
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID to seed")
    parser.add_argument(
        "--output-dir",
        default="tmp/uat-seed",
        help="Directory for generated UAT snapshot artifacts",
    )
    parser.add_argument(
        "--include-demo-payloads",
        action="store_true",
        help="Also generate demo payment payload JSON files for operator walkthroughs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended operations without writing DB/file outputs",
    )
    return parser.parse_args()


def _db_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/kuberatreasury",
    )


def _with_connect_timeout(url: str, seconds: int = 10) -> str:
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgresql"):
        return url
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params.setdefault("connect_timeout", str(seconds))
    return urlunparse(parsed._replace(query=urlencode(params)))


def seed_payment_policies(tenant_id: uuid.UUID, dry_run: bool) -> None:
    sql = text(
        """
        INSERT INTO payment_policies (
            payment_policy_id,
            tenant_id,
            policy_name,
            currency_code,
            threshold_amount,
            required_approvals,
            is_active
        )
        VALUES (
            :payment_policy_id,
            :tenant_id,
            :policy_name,
            :currency_code,
            :threshold_amount,
            :required_approvals,
            true
        )
        ON CONFLICT (tenant_id, policy_name, currency_code)
        DO UPDATE SET
            threshold_amount = EXCLUDED.threshold_amount,
            required_approvals = EXCLUDED.required_approvals,
            is_active = true
        """
    )

    if dry_run:
        for policy in DEFAULT_POLICIES:
            print(f"[DRY-RUN] Upsert policy: {policy['policy_name']} for tenant {tenant_id}")
        return

    engine = create_engine(_with_connect_timeout(_db_url(), seconds=10), future=True)
    with engine.begin() as conn:
        for policy in DEFAULT_POLICIES:
            conn.execute(
                sql,
                {
                    "payment_policy_id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_id),
                    "policy_name": policy["policy_name"],
                    "currency_code": policy["currency_code"],
                    "threshold_amount": policy["threshold_amount"],
                    "required_approvals": policy["required_approvals"],
                },
            )

    print(f"Upserted {len(DEFAULT_POLICIES)} payment policy rows for tenant {tenant_id}.")


def write_sanctions_snapshot(tenant_id: uuid.UUID, output_dir: Path, dry_run: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"sanctions_snapshot_{tenant_id}.json"

    payload: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "source": "UAT bootstrap default set",
        "ofsi_fuzzy_threshold": 85,
        "proximity_log_threshold": 60,
        "entities": DEFAULT_SANCTIONS_ENTITIES,
        "note": "USER ACTION REQUIRED: replace this default snapshot with latest OFSI UK consolidated sanctions list before production.",
    }

    if dry_run:
        print(f"[DRY-RUN] Would write sanctions snapshot: {file_path}")
        return file_path

    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote sanctions snapshot: {file_path}")
    return file_path


def write_demo_payloads(tenant_id: uuid.UUID, output_dir: Path, dry_run: bool) -> None:
    payload = {
        "tenant_id": str(tenant_id),
        "initiator_role": "treasury_analyst",
        "approval_expectation": ["treasury_manager", "compliance_officer"],
        "examples": [
            {
                "name": "standard_gbp_payment",
                "amount": "5000.00",
                "currency_code": "GBP",
                "urgent": False,
                "same_day": False,
            },
            {
                "name": "urgent_non_gbp_payment",
                "amount": "25000.00",
                "currency_code": "USD",
                "urgent": True,
                "same_day": True,
            },
        ],
        "note": "USER ACTION REQUIRED: replace counterparty/account identifiers with tenant-specific IDs.",
    }

    file_path = output_dir / f"demo_payment_payloads_{tenant_id}.json"
    if dry_run:
        print(f"[DRY-RUN] Would write demo payloads: {file_path}")
        return

    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote demo payloads: {file_path}")


def main() -> None:
    args = parse_args()
    try:
        tenant_id = uuid.UUID(args.tenant_id)
    except ValueError as exc:
        raise SystemExit(f"Invalid --tenant-id: {exc}")

    output_dir = Path(args.output_dir)

    print("Starting UAT Phase 4 bootstrap...")
    try:
        seed_payment_policies(tenant_id=tenant_id, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print("USER ACTION REQUIRED: unable to seed payment_policies table.")
        print(f"Reason: {exc}")
        print("Ensure DATABASE_URL points to the target Postgres environment and tenant exists.")

    write_sanctions_snapshot(tenant_id=tenant_id, output_dir=output_dir, dry_run=args.dry_run)

    if args.include_demo_payloads:
        write_demo_payloads(tenant_id=tenant_id, output_dir=output_dir, dry_run=args.dry_run)

    print("Bootstrap complete.")


if __name__ == "__main__":
    main()
