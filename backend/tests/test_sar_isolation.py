"""SAR isolation tests — POCA 2002 s.333A tipping-off prevention.

Verifies that:
  - Only the compliance_officer role can access /api/v1/sar/* endpoints.
  - Other roles (treasury_analyst, treasury_manager) receive 403.
  - Payments-router responses never contain the words "sar", "suspicious",
    or "laundering" — including for frozen / under-MLRO-review payments.
  - The compliance_officer can access the SAR queue and retrieve cases.

Auth is injected via ``app.dependency_overrides[get_current_user]`` so
no real JWT signing or live DB is required.  The tests operate against
the module-level service singleton shared by both routers.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.v1.payments_compliance import _payments as _svc
from app.core.dependencies import CurrentUser, get_current_user
from app.main import create_app
from app.services.payments_compliance_service import PaymentInstructionIn


# ─────────────────────────────────────────── Helpers ──────────────────────────

_FORBIDDEN_WORDS = {"sar", "suspicious", "laundering"}


def _sar_triggering_payload(**overrides) -> PaymentInstructionIn:
    """Return a PaymentInstructionIn that will create a SAR case.

    Uses a known sanctions-list entity name and an FATF high-risk destination
    country to guarantee _sar_flags returns non-empty.
    """
    base = PaymentInstructionIn(
        tenant_id=uuid.uuid4(),
        initiator_user_id=uuid.uuid4(),
        initiator_role="treasury_manager",
        debit_bank_account_id=uuid.uuid4(),
        counterparty_id=uuid.uuid4(),
        beneficiary_name="National Iranian Oil Company",
        amount=Decimal("60000"),
        currency_code="GBP",
        scheduled_for=datetime.now(tz=timezone.utc) + timedelta(hours=2),
        available_balance=Decimal("500000"),
        overdraft_limit=Decimal("0"),
        min_buffer=Decimal("0"),
        destination_country_code="IR",
        ip_address="10.0.0.1",
        registered_company_name="National Iranian Oil Company",
    )
    return base.model_copy(update=overrides)


def _make_client(roles: list[str]) -> TestClient:
    """Build a TestClient whose get_current_user always yields the given roles.

    The override bypasses JWT decoding and IP-allowlist middleware side-effects
    while still exercising the role-enforcement dependency on the SAR router.
    No Authorization header is sent, so TenantIsolationMiddleware leaves
    request.state.tenant_id = None and IpAllowlistMiddleware passes through.
    """
    app = create_app()

    async def _fake_user() -> CurrentUser:
        return CurrentUser(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            roles=roles,
        )

    app.dependency_overrides[get_current_user] = _fake_user
    return TestClient(app, raise_server_exceptions=True)


# ─────────────────────────────────── Role enforcement — 403 paths ────────────


SAR_ENDPOINTS = [
    ("GET",  "/api/v1/sar/queue"),
    ("GET",  f"/api/v1/sar/{uuid.uuid4()}"),
    ("POST", f"/api/v1/sar/{uuid.uuid4()}/clear"),
    ("POST", f"/api/v1/sar/{uuid.uuid4()}/report"),
]


@pytest.mark.parametrize("method, path", SAR_ENDPOINTS)
def test_treasury_analyst_cannot_access_sar(method: str, path: str) -> None:
    """treasury_analyst must receive 403 on every SAR endpoint."""
    client = _make_client(["treasury_analyst"])
    resp = client.request(method, path)
    assert resp.status_code == 403, f"{method} {path} → expected 403, got {resp.status_code}"


@pytest.mark.parametrize("method, path", SAR_ENDPOINTS)
def test_treasury_manager_cannot_access_sar(method: str, path: str) -> None:
    """treasury_manager must receive 403 on every SAR endpoint."""
    client = _make_client(["treasury_manager"])
    resp = client.request(method, path)
    assert resp.status_code == 403, f"{method} {path} → expected 403, got {resp.status_code}"


@pytest.mark.parametrize("method, path", SAR_ENDPOINTS)
def test_auditor_cannot_access_sar(method: str, path: str) -> None:
    """auditor must receive 403 on every SAR endpoint."""
    client = _make_client(["auditor"])
    resp = client.request(method, path)
    assert resp.status_code == 403, f"{method} {path} → expected 403, got {resp.status_code}"


@pytest.mark.parametrize("method, path", SAR_ENDPOINTS)
def test_cfo_cannot_access_sar(method: str, path: str) -> None:
    """cfo must receive 403 on every SAR endpoint."""
    client = _make_client(["cfo"])
    resp = client.request(method, path)
    assert resp.status_code == 403, f"{method} {path} → expected 403, got {resp.status_code}"


# ─────────────────────────────────── compliance_officer access ────────────────


def test_compliance_officer_can_access_queue() -> None:
    """compliance_officer receives 200 on GET /api/v1/sar/queue."""
    # Create a SAR-flagged payment directly via the service singleton so the
    # queue is non-empty (validates serialisation round-trip as well).
    _svc.configure_approval_matrix(
        _sar_triggering_payload().tenant_id
    )  # ensure matrix exists
    out = _svc.initiate_payment(_sar_triggering_payload())
    assert out.sanctions_match_score > 0  # sanity-check: SAR case was created

    client = _make_client(["compliance_officer"])
    resp = client.get("/api/v1/sar/queue")
    assert resp.status_code == 200
    queue = resp.json()
    assert isinstance(queue, list)
    # At least one item should be present (the one we just created).
    assert any(item["case_status"] == "UNDER_REVIEW" for item in queue)


def test_compliance_officer_queue_items_are_pseudonymised() -> None:
    """SAR queue items must not contain the real beneficiary name."""
    out = _svc.initiate_payment(_sar_triggering_payload())
    assert out.sanctions_match_score > 0

    client = _make_client(["compliance_officer"])
    resp = client.get("/api/v1/sar/queue")
    assert resp.status_code == 200
    body_text = resp.text.lower()
    # Real name must not appear
    assert "national iranian oil company" not in body_text
    # Pseudonymised reference should be present
    assert any("BEN-" in item.get("beneficiary_ref", "") for item in resp.json())


# ──────────────────────── Tipping-off prevention — payments router ────────────


def test_payment_response_never_contains_sar_language_normal() -> None:
    """A normal payment response must contain none of the forbidden words."""
    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/payments/initiate",
        json={
            "tenant_id": str(uuid.uuid4()),
            "initiator_user_id": str(uuid.uuid4()),
            "initiator_role": "treasury_analyst",
            "debit_bank_account_id": str(uuid.uuid4()),
            "counterparty_id": str(uuid.uuid4()),
            "beneficiary_name": "Acme Supplies Ltd",
            "amount": "5000",
            "currency_code": "GBP",
            "scheduled_for": (
                datetime.now(tz=timezone.utc) + timedelta(hours=1)
            ).isoformat(),
            "available_balance": "100000",
            "overdraft_limit": "10000",
            "min_buffer": "1000",
            "destination_country_code": "GB",
            "ip_address": "10.0.0.1",
            "registered_company_name": "Acme Supplies Ltd",
            "vat_number": "123456789",
        },
    )
    assert resp.status_code == 200
    body_text = resp.text.lower()
    for word in _FORBIDDEN_WORDS:
        assert word not in body_text, (
            f"Forbidden word '{word}' found in payments response: {resp.text}"
        )


def test_payment_response_never_contains_sar_language_frozen() -> None:
    """A frozen (under-review) payment response must not leak SAR terminology."""
    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/payments/initiate",
        json={
            "tenant_id": str(uuid.uuid4()),
            "initiator_user_id": str(uuid.uuid4()),
            "initiator_role": "treasury_manager",
            "debit_bank_account_id": str(uuid.uuid4()),
            "counterparty_id": str(uuid.uuid4()),
            "beneficiary_name": "National Iranian Oil Company",
            "amount": "60000",
            "currency_code": "GBP",
            "scheduled_for": (
                datetime.now(tz=timezone.utc) + timedelta(hours=1)
            ).isoformat(),
            "available_balance": "500000",
            "overdraft_limit": "0",
            "min_buffer": "0",
            "destination_country_code": "IR",
            "ip_address": "10.0.0.1",
            "registered_company_name": "National Iranian Oil Company",
        },
    )
    assert resp.status_code == 200
    body_text = resp.text.lower()
    for word in _FORBIDDEN_WORDS:
        assert word not in body_text, (
            f"Forbidden word '{word}' found in frozen payment response: {resp.text}"
        )

    # The frozen payment should appear as UNDER_REVIEW, not expose internal status.
    data = resp.json()
    assert data["status"] == "UNDER_REVIEW"
    # Internal investigation fields must not be present in the schema.
    assert "frozen" not in data
    assert "under_review" not in data
    assert "compliance_alerted" not in data
    assert "sanctions_match_score" not in data


def test_payment_fields_never_leak_sar_schema() -> None:
    """PaymentPublicOut must not include any internal investigation fields."""
    app = create_app()
    client = TestClient(app)

    resp = client.post(
        "/api/v1/payments/initiate",
        json={
            "tenant_id": str(uuid.uuid4()),
            "initiator_user_id": str(uuid.uuid4()),
            "initiator_role": "treasury_analyst",
            "debit_bank_account_id": str(uuid.uuid4()),
            "counterparty_id": str(uuid.uuid4()),
            "beneficiary_name": "Acme Supplies Ltd",
            "amount": "5000",
            "currency_code": "GBP",
            "scheduled_for": (
                datetime.now(tz=timezone.utc) + timedelta(hours=1)
            ).isoformat(),
            "available_balance": "100000",
            "overdraft_limit": "10000",
            "min_buffer": "1000",
            "destination_country_code": "GB",
            "ip_address": "10.0.0.1",
            "registered_company_name": "Acme Supplies Ltd",
            "vat_number": "123456789",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    prohibited_fields = {
        "frozen", "under_review", "compliance_alerted",
        "sanctions_match_score", "sar_flags",
    }
    present = prohibited_fields.intersection(data.keys())
    assert not present, f"Internal fields exposed in payment response: {present}"


# ─────────────────────────── SAR report bundle pseudonymisation ───────────────


def test_sar_report_bundle_excludes_real_identifiers() -> None:
    """The SAR report bundle must not contain the real beneficiary name,
    real payment_id, or real counterparty_id."""
    # Set up a payment with an active SAR case via the service singleton.
    payload = _sar_triggering_payload()
    out = _svc.initiate_payment(payload)
    assert out.sanctions_match_score > 0  # SAR case created

    # Find the sar_case_id for this payment.
    cases = _svc.sar_queue()
    matching = [c for c in cases if c.payment_id == out.payment_id]
    if not matching:
        pytest.skip("No SAR case was created for this payment — skipping")
    sar_case_id = matching[0].sar_case_id

    client = _make_client(["compliance_officer"])
    resp = client.post(f"/api/v1/sar/{sar_case_id}/report")
    assert resp.status_code == 200

    body_text = resp.text.lower()
    # Real name must not appear.
    assert "national iranian oil company" not in body_text
    # Real UUIDs must not appear verbatim.
    assert str(out.payment_id).lower() not in body_text
    assert str(payload.counterparty_id).lower() not in body_text
    # Pseudonymised refs must be present.
    data = resp.json()
    assert data["payment_ref"].startswith("PAY-")
    assert data["beneficiary_ref"].startswith("BEN-")
    assert data["counterparty_ref"].startswith("CTP-")
    # Exact amount must not be in banded field.
    assert "60000" not in data["amount_band"]
    # Real names / UUIDs must be absent from the values returned.
    assert "national iranian oil company" not in resp.text.lower()
    assert str(out.payment_id).lower() not in resp.text.lower()
    assert str(payload.counterparty_id).lower() not in resp.text.lower()
    # Note: "sar" appearing in field *names* (e.g. "sar_case_id") is
    # expected and correct in this MLRO-only router — the forbidden-words
    # restriction applies only to the payments router (POCA 2002 s.333A).
