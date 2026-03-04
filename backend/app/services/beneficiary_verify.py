"""Beneficiary verification service.

Before a payment to a new beneficiary can be approved, this service runs two
external checks:

1. **Companies House** — confirms the company name matches and the company
   is still *active*.
2. **HMRC VAT** — confirms the VAT number is valid and the trader name
   matches the submitted beneficiary name.

Both checks are mandatory.  The overall ``action`` is:

* ``"APPROVED"``       — both checks pass (ratios ≥ 0.85, active, VAT valid)
* ``"BLOCKED"``        — company is dissolved / struck-off (payment cannot proceed)
* ``"MANUAL_REVIEW"``  — any other failure (low ratio, VAT mismatch, API error)

Results are cached for 24 hours (per-tenant, per beneficiary name + VAT number)
using an in-process TTL dict.  A Redis URL can be set via ``settings.REDIS_URL``
for production deployments (the cache adapter is swappable).

Every check is logged to the ``beneficiary_verification_log`` ORM table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Literal

import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import BeneficiaryVerificationLog

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CH_SEARCH_URL = "https://api.company-information.service.gov.uk/search/companies"
_HMRC_VAT_URL = (
    "https://api.service.hmrc.gov.uk/organisations/vat/check-vat-number/lookup"
)
_NAME_MATCH_THRESHOLD = 0.85
_DISSOLVED_STATUSES = {"dissolved", "liquidation", "receivership", "struck-off"}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class BeneficiaryVerifyRequest(BaseModel):
    """Input payload for a beneficiary verification check."""

    tenant_id: uuid.UUID
    requested_by_user_id: uuid.UUID
    company_name: str
    vat_number: str | None = None


ActionType = Literal["APPROVED", "MANUAL_REVIEW", "BLOCKED"]


class BeneficiaryVerifyResult(BaseModel):
    """Result of a beneficiary verification check."""

    companies_house_match: float
    companies_house_status: str
    vat_valid: bool
    vat_name_match: float
    verified: bool
    checked_at: datetime
    action: ActionType
    alert_compliance_officer: bool


# ---------------------------------------------------------------------------
# In-process TTL cache
# ---------------------------------------------------------------------------

class _VerificationCache:
    """Simple in-process dict cache with per-entry TTL.

    Production deployments should replace this with a Redis-backed
    implementation by configuring ``settings.REDIS_URL``.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[BeneficiaryVerifyResult, datetime]] = {}
        self._ttl = timedelta(hours=24)

    def _key(
        self, tenant_id: uuid.UUID, company_name: str, vat_number: str | None
    ) -> str:
        return f"{tenant_id}:{company_name.lower()}:{vat_number or ''}"

    def get(
        self, tenant_id: uuid.UUID, company_name: str, vat_number: str | None
    ) -> BeneficiaryVerifyResult | None:
        key = self._key(tenant_id, company_name, vat_number)
        entry = self._store.get(key)
        if entry is None:
            return None
        result, expires_at = entry
        if datetime.now(timezone.utc) > expires_at:
            del self._store[key]
            return None
        return result

    def set(
        self,
        tenant_id: uuid.UUID,
        company_name: str,
        vat_number: str | None,
        result: BeneficiaryVerifyResult,
    ) -> None:
        key = self._key(tenant_id, company_name, vat_number)
        self._store[key] = (result, datetime.now(timezone.utc) + self._ttl)

    def invalidate(
        self, tenant_id: uuid.UUID, company_name: str, vat_number: str | None
    ) -> None:
        key = self._key(tenant_id, company_name, vat_number)
        self._store.pop(key, None)


# Module-level singleton — shared across requests within the same process.
_cache = _VerificationCache()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BeneficiaryVerifyService:
    """Verify a beneficiary via Companies House and HMRC VAT APIs."""

    # Allows tests to inject a custom httpx client.
    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(self, request: BeneficiaryVerifyRequest) -> BeneficiaryVerifyResult:
        """Run both checks synchronously and return the combined result.

        Returns cached result if the same (tenant, company, VAT) was checked
        within the last 24 hours.
        """
        cached = _cache.get(request.tenant_id, request.company_name, request.vat_number)
        if cached is not None:
            return cached

        result = self._run_checks(request)
        _cache.set(request.tenant_id, request.company_name, request.vat_number, result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client_ctx(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=15.0)

    def _ratio(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

    def _run_checks(self, request: BeneficiaryVerifyRequest) -> BeneficiaryVerifyResult:
        ch_match, ch_status = self._check_companies_house(request.company_name)
        vat_valid, vat_name_match = self._check_vat(
            request.vat_number, request.company_name
        )

        # Determine action
        normalised_status = ch_status.lower()
        is_dissolved = any(s in normalised_status for s in _DISSOLVED_STATUSES)

        if is_dissolved:
            action: ActionType = "BLOCKED"
            verified = False
        elif (
            ch_match >= _NAME_MATCH_THRESHOLD
            and "active" in normalised_status
            and vat_valid
            and vat_name_match >= _NAME_MATCH_THRESHOLD
        ):
            action = "APPROVED"
            verified = True
        else:
            action = "MANUAL_REVIEW"
            verified = False

        alert_compliance_officer = not verified

        return BeneficiaryVerifyResult(
            companies_house_match=ch_match,
            companies_house_status=ch_status,
            vat_valid=vat_valid,
            vat_name_match=vat_name_match,
            verified=verified,
            checked_at=datetime.now(timezone.utc),
            action=action,
            alert_compliance_officer=alert_compliance_officer,
        )

    def _check_companies_house(self, company_name: str) -> tuple[float, str]:
        """Query Companies House and return (name_ratio, company_status).

        Returns (0.0, "unknown") on any API error so the caller can handle it
        as MANUAL_REVIEW rather than crashing.
        """
        try:
            ctx = self._client_ctx()
            # If using an injected test client, avoid context-manager issues.
            if self._client is not None:
                resp = ctx.get(
                    _CH_SEARCH_URL,
                    params={"q": company_name, "items_per_page": 5},
                )
            else:
                with ctx as client:
                    resp = client.get(
                        _CH_SEARCH_URL,
                        params={"q": company_name, "items_per_page": 5},
                    )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            items: list[dict] = data.get("items", [])
            if not items:
                return 0.0, "not_found"
            top = items[0]
            top_title: str = top.get("title", "")
            status: str = top.get("company_status", "unknown")
            ratio = self._ratio(company_name, top_title)
            return round(ratio, 4), status
        except Exception:  # network / parse error
            return 0.0, "error"

    def _check_vat(
        self, vat_number: str | None, beneficiary_name: str
    ) -> tuple[bool, float]:
        """Query HMRC VAT check and return (is_valid, name_ratio).

        Returns (False, 0.0) when no VAT number is supplied or on any error.
        """
        if not vat_number:
            return False, 0.0

        # Normalise: strip spaces / GB prefix
        normalised = vat_number.strip().upper().removeprefix("GB").replace(" ", "")

        try:
            ctx = self._client_ctx()
            if self._client is not None:
                resp = ctx.get(
                    _HMRC_VAT_URL,
                    params={"targetVrn": normalised},
                    headers={"Accept": "application/json"},
                )
            else:
                with ctx as client:
                    resp = client.get(
                        _HMRC_VAT_URL,
                        params={"targetVrn": normalised},
                        headers={"Accept": "application/json"},
                    )
            if resp.status_code == 404:
                return False, 0.0
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            target: dict = data.get("target", {})
            trader_name: str = target.get("name", "")
            if not trader_name:
                return False, 0.0
            ratio = self._ratio(beneficiary_name, trader_name)
            return True, round(ratio, 4)
        except Exception:
            return False, 0.0


# ---------------------------------------------------------------------------
# Async DB logger
# ---------------------------------------------------------------------------


async def log_verification(
    db: AsyncSession,
    request: BeneficiaryVerifyRequest,
    result: BeneficiaryVerifyResult,
) -> BeneficiaryVerificationLog:
    """Persist an immutable verification log record and flush (does not commit)."""
    entry = BeneficiaryVerificationLog(
        tenant_id=request.tenant_id,
        requested_by_user_id=request.requested_by_user_id,
        company_name=request.company_name,
        vat_number=request.vat_number,
        companies_house_match=Decimal(str(result.companies_house_match)),
        companies_house_status=result.companies_house_status,
        vat_valid=result.vat_valid,
        vat_name_match=Decimal(str(result.vat_name_match)),
        verified=result.verified,
        action=result.action,
        alert_compliance_officer=result.alert_compliance_officer,
        checked_at=result.checked_at,
    )
    db.add(entry)
    await db.flush()
    return entry
