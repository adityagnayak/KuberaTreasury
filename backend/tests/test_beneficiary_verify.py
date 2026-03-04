"""Tests for app.services.beneficiary_verify.

All external HTTP calls (Companies House, HMRC VAT) are mocked.

Scenarios:
- All checks pass → APPROVED, verified=True
- Company name ratio < 0.85 → MANUAL_REVIEW, alert compliance officer
- Company dissolved/struck-off → BLOCKED, verified=False
- Invalid / unknown VAT number (HTTP 404) → MANUAL_REVIEW
- No VAT number supplied → MANUAL_REVIEW
- Cache hit returns same result without re-calling HTTP
- log_verification writes a BeneficiaryVerificationLog row to DB
- Non-treasury_analyst role gets HTTP 403 on the endpoint
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.database import get_db
from app.main import create_app
from app.models import BeneficiaryVerificationLog
from app.services.beneficiary_verify import (
    BeneficiaryVerifyRequest,
    BeneficiaryVerifyResult,
    BeneficiaryVerifyService,
    _cache,
    log_verification,
)


# ─────────────────────────────────────────────────── Mock helpers ──────────────


class _MockResponse:
    """Fake httpx response."""

    def __init__(self, data: Any, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def json(self) -> Any:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                message=f"HTTP {self.status_code}",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )


class _MockHttpClient:
    """Fake httpx.Client that returns pre-canned CH and VAT responses."""

    def __init__(
        self,
        ch_data: dict | None = None,
        ch_status: int = 200,
        vat_data: dict | None = None,
        vat_status: int = 200,
    ) -> None:
        self._ch = _MockResponse(ch_data or {}, ch_status)
        self._vat = _MockResponse(vat_data or {}, vat_status)

    def get(self, url: str, **kwargs) -> _MockResponse:
        if "company-information" in url:
            return self._ch
        return self._vat


def _ch_response(title: str, status: str = "active") -> dict:
    return {"items": [{"title": title, "company_status": status}]}


def _vat_response(name: str) -> dict:
    return {"target": {"name": name, "vatNumber": "123456789"}}


def _make_request(
    company: str = "Acme Supplies Ltd",
    vat: str | None = "123456789",
    tenant_id: uuid.UUID | None = None,
) -> BeneficiaryVerifyRequest:
    return BeneficiaryVerifyRequest(
        tenant_id=tenant_id or uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        company_name=company,
        vat_number=vat,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 1. Both checks pass → APPROVED
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_approved_when_both_checks_pass() -> None:
    client = _MockHttpClient(
        ch_data=_ch_response("Acme Supplies Ltd", "active"),
        vat_data=_vat_response("Acme Supplies Ltd"),
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request())

    assert result.action == "APPROVED"
    assert result.verified is True
    assert result.companies_house_match >= 0.85
    assert result.vat_valid is True
    assert result.vat_name_match >= 0.85
    assert result.alert_compliance_officer is False
    assert isinstance(result.checked_at, datetime)


# ═════════════════════════════════════════════════════════════════════════════
# 2. Company name mismatch → MANUAL_REVIEW
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_manual_review_on_name_mismatch() -> None:
    # CH returns a completely different company
    client = _MockHttpClient(
        ch_data=_ch_response("Totally Different Corp", "active"),
        vat_data=_vat_response("Acme Supplies Ltd"),
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request("Acme Supplies Ltd"))

    assert result.action == "MANUAL_REVIEW"
    assert result.verified is False
    assert result.companies_house_match < 0.85
    assert result.alert_compliance_officer is True


# ═════════════════════════════════════════════════════════════════════════════
# 3. Dissolved company → BLOCKED
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_blocked_on_dissolved_company() -> None:
    client = _MockHttpClient(
        ch_data=_ch_response("Acme Supplies Ltd", "dissolved"),
        vat_data=_vat_response("Acme Supplies Ltd"),
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request("Acme Supplies Ltd"))

    assert result.action == "BLOCKED"
    assert result.verified is False
    assert "dissolved" in result.companies_house_status.lower()
    assert result.alert_compliance_officer is True


def test_verify_blocked_on_struck_off_company() -> None:
    client = _MockHttpClient(
        ch_data=_ch_response("Acme Supplies Ltd", "struck-off"),
        vat_data=_vat_response("Acme Supplies Ltd"),
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request("Acme Supplies Ltd"))

    assert result.action == "BLOCKED"
    assert result.verified is False


# ═════════════════════════════════════════════════════════════════════════════
# 4. Invalid / not-found VAT number → MANUAL_REVIEW
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_manual_review_on_invalid_vat_404() -> None:
    client = _MockHttpClient(
        ch_data=_ch_response("Acme Supplies Ltd", "active"),
        vat_status=404,
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request("Acme Supplies Ltd", vat="BADVATNUMBER"))

    assert result.action == "MANUAL_REVIEW"
    assert result.vat_valid is False
    assert result.vat_name_match == 0.0
    assert result.verified is False
    assert result.alert_compliance_officer is True


# ═════════════════════════════════════════════════════════════════════════════
# 5. No VAT number supplied → MANUAL_REVIEW
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_manual_review_when_no_vat_supplied() -> None:
    client = _MockHttpClient(
        ch_data=_ch_response("Acme Supplies Ltd", "active"),
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request("Acme Supplies Ltd", vat=None))

    assert result.vat_valid is False
    assert result.action == "MANUAL_REVIEW"
    assert result.verified is False


# ═════════════════════════════════════════════════════════════════════════════
# 6. VAT trader name mismatch → MANUAL_REVIEW
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_manual_review_on_vat_name_mismatch() -> None:
    client = _MockHttpClient(
        ch_data=_ch_response("Acme Supplies Ltd", "active"),
        vat_data=_vat_response("Completely Different Trader Name"),
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request("Acme Supplies Ltd"))

    assert result.vat_valid is True  # VAT number OK, but name doesn't match
    assert result.vat_name_match < 0.85
    assert result.action == "MANUAL_REVIEW"
    assert result.verified is False


# ═════════════════════════════════════════════════════════════════════════════
# 7. Cache hit — second call does not invoke HTTP
# ═════════════════════════════════════════════════════════════════════════════


def test_cache_hit_returns_same_result_without_http() -> None:
    tenant_id = uuid.uuid4()  # unique so no prior cache entry
    call_count = 0

    class CountingClient:
        def get(self, url: str, **kwargs):
            nonlocal call_count
            call_count += 1
            if "company-information" in url:
                return _MockResponse(_ch_response("Acme Supplies Ltd", "active"))
            return _MockResponse(_vat_response("Acme Supplies Ltd"))

    svc = BeneficiaryVerifyService(http_client=CountingClient())
    req = _make_request(tenant_id=tenant_id)

    result1 = svc.verify(req)
    result2 = svc.verify(req)

    assert call_count == 2  # 1 CH + 1 VAT call once; second call hits cache
    assert result1.action == result2.action
    assert result1.checked_at == result2.checked_at

    # Cleanup
    _cache.invalidate(tenant_id, req.company_name, req.vat_number)


# ═════════════════════════════════════════════════════════════════════════════
# 8. Companies House returns no items → MANUAL_REVIEW
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_manual_review_when_ch_returns_no_items() -> None:
    client = _MockHttpClient(
        ch_data={"items": []},
        vat_data=_vat_response("Acme Supplies Ltd"),
    )
    svc = BeneficiaryVerifyService(http_client=client)
    result = svc.verify(_make_request())

    assert result.companies_house_match == 0.0
    assert result.companies_house_status == "not_found"
    assert result.action == "MANUAL_REVIEW"


# ═════════════════════════════════════════════════════════════════════════════
# 9. Companies House API error → MANUAL_REVIEW (not a crash)
# ═════════════════════════════════════════════════════════════════════════════


def test_verify_manual_review_on_ch_api_error() -> None:
    class ErrorClient:
        def get(self, url: str, **kwargs):
            if "company-information" in url:
                raise httpx.ConnectError("timeout")
            return _MockResponse(_vat_response("Acme Supplies Ltd"))

    svc = BeneficiaryVerifyService(http_client=ErrorClient())
    result = svc.verify(_make_request())

    assert result.companies_house_status == "error"
    assert result.companies_house_match == 0.0
    assert result.action == "MANUAL_REVIEW"


# ═════════════════════════════════════════════════════════════════════════════
# 10. log_verification writes to DB
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_log_verification_writes_row(db: AsyncSession, tenant) -> None:
    req = BeneficiaryVerifyRequest(
        tenant_id=tenant.tenant_id,
        requested_by_user_id=uuid.uuid4(),
        company_name="Acme Supplies Ltd",
        vat_number="123456789",
    )
    fake_result = BeneficiaryVerifyResult(
        companies_house_match=0.95,
        companies_house_status="active",
        vat_valid=True,
        vat_name_match=0.96,
        verified=True,
        checked_at=datetime.now(timezone.utc),
        action="APPROVED",
        alert_compliance_officer=False,
    )

    entry = await log_verification(db, req, fake_result)
    await db.flush()

    row = (
        await db.execute(
            select(BeneficiaryVerificationLog).where(
                BeneficiaryVerificationLog.log_id == entry.log_id
            )
        )
    ).scalars().one()

    assert row.company_name == "Acme Supplies Ltd"
    assert row.vat_number == "123456789"
    assert row.verified is True
    assert row.action == "APPROVED"
    assert row.alert_compliance_officer is False
    assert row.tenant_id == tenant.tenant_id
    assert Decimal(str(row.companies_house_match)) == Decimal("0.95")


@pytest.mark.asyncio
async def test_log_verification_manual_review_sets_alert(
    db: AsyncSession, tenant
) -> None:
    req = BeneficiaryVerifyRequest(
        tenant_id=tenant.tenant_id,
        requested_by_user_id=uuid.uuid4(),
        company_name="Unknown Corp",
        vat_number=None,
    )
    fake_result = BeneficiaryVerifyResult(
        companies_house_match=0.4,
        companies_house_status="active",
        vat_valid=False,
        vat_name_match=0.0,
        verified=False,
        checked_at=datetime.now(timezone.utc),
        action="MANUAL_REVIEW",
        alert_compliance_officer=True,
    )

    entry = await log_verification(db, req, fake_result)
    await db.flush()

    row = (
        await db.execute(
            select(BeneficiaryVerificationLog).where(
                BeneficiaryVerificationLog.log_id == entry.log_id
            )
        )
    ).scalars().one()

    assert row.verified is False
    assert row.action == "MANUAL_REVIEW"
    assert row.alert_compliance_officer is True
    assert row.vat_number is None


# ═════════════════════════════════════════════════════════════════════════════
# 11. API endpoint role enforcement
# ═════════════════════════════════════════════════════════════════════════════


def _make_app_with_role(roles: list[str]):
    app = create_app()
    actor = CurrentUser(
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        roles=roles,
    )
    app.dependency_overrides[get_current_user] = lambda: actor
    from unittest.mock import AsyncMock  # noqa: PLC0415
    async def _mock_db():
        yield AsyncMock(spec=AsyncSession)
    app.dependency_overrides[get_db] = _mock_db
    return app


def test_endpoint_forbidden_for_auditor_role() -> None:
    app = _make_app_with_role(["auditor"])
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/payments/beneficiaries/verify",
            json={
                "tenant_id": str(uuid.uuid4()),
                "requested_by_user_id": str(uuid.uuid4()),
                "company_name": "Acme Supplies Ltd",
                "vat_number": "123456789",
            },
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_endpoint_forbidden_for_empty_roles() -> None:
    app = _make_app_with_role([])
    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/v1/payments/beneficiaries/verify",
            json={
                "tenant_id": str(uuid.uuid4()),
                "requested_by_user_id": str(uuid.uuid4()),
                "company_name": "Acme Supplies Ltd",
            },
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ═════════════════════════════════════════════════════════════════════════════
# 12. VAT normalisation — GB prefix stripped
# ═════════════════════════════════════════════════════════════════════════════


def test_vat_gb_prefix_is_stripped_before_lookup() -> None:
    seen_params: list[dict] = []

    class RecordingClient:
        def get(self, url: str, **kwargs):
            if "check-vat-number" in url:
                seen_params.append(kwargs.get("params", {}))
                return _MockResponse(_vat_response("Acme Supplies Ltd"))
            return _MockResponse(_ch_response("Acme Supplies Ltd", "active"))

    svc = BeneficiaryVerifyService(http_client=RecordingClient())
    svc.verify(_make_request(vat="GB 123 456 789"))

    assert seen_params, "VAT endpoint must have been called"
    target_vrn = seen_params[0].get("targetVrn", "")
    assert not target_vrn.startswith("GB"), "GB prefix must be stripped"
    assert " " not in target_vrn, "Spaces must be removed from VAT number"
