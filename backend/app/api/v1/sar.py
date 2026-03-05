"""SAR (Suspicious Activity Report) router — MLRO-only workspace.

**POCA 2002 s.333A — tipping-off is a criminal offence.**

This module is intentionally isolated from the payments router:

- All endpoints require the ``compliance_officer`` role enforced by a
  *dedicated* dependency that is not shared with any other router.
- No SAR case IDs, flag reasons, or MLRO decision details are ever
  included in payments-router responses.
- All identifiers returned from this router are pseudonymised; real
  account numbers, IBANs, and beneficiary names are never exposed in
  the report bundle.

Router prefix: /api/v1/sar
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.dependencies import CurrentUser, get_current_user

# ── Shared service instance (same object used by the payments router) ─────────
# Imported from the payments router module so both routers operate on the
# same in-memory store.  sar.py → payments_compliance.py is a one-way
# dependency with no circular imports.
from app.api.v1.payments_compliance import _payments  # noqa: PLC0415

router = APIRouter(prefix="/sar", tags=["SAR"])


# ──────────────────────────── Dedicated auth dependency ───────────────────────


def _require_compliance_officer(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Enforce compliance_officer role — raises 403 for every other role.

    This dependency is intentionally NOT shared with the payments router so
    that a misconfiguration of one cannot widen access to the other.
    """
    if "compliance_officer" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden",
        )
    return user


SarUser = Annotated[CurrentUser, Depends(_require_compliance_officer)]


# ──────────────────────────── Pseudonymisation helpers ────────────────────────


def _pseudo(value: str, prefix: str = "REF") -> str:
    """Stable pseudonymous reference — deterministic SHA-256 prefix."""
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:12].upper()}"


def _amount_band(amount: Decimal) -> str:
    """Return a banded amount string instead of the exact figure."""
    thresholds = [1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
    prev = 0
    for t in thresholds:
        if amount <= Decimal(str(t)):
            return f"{prev:,}-{t:,}"
        prev = t
    return "1,000,000+"


# ────────────────────────────── Response schemas ──────────────────────────────


class SarQueueItemOut(BaseModel):
    """Minimal queue entry — enough for the MLRO to triage, nothing more."""
    sar_case_id: uuid.UUID
    queued_at: datetime
    flag_count: int
    amount_band: str
    beneficiary_ref: str        # pseudonymised
    currency_code: str
    case_status: str


class SarCaseOut(BaseModel):
    """Full SAR case view — only served to compliance_officer."""
    sar_case_id: uuid.UUID
    queued_at: datetime
    case_status: str
    trigger_reasons: list[str]  # flag.flag values — process codes, not names
    trigger_details: list[str]  # flag.detail — provided to MLRO only
    mlro_user_id: uuid.UUID | None


class SarClearOut(BaseModel):
    sar_case_id: uuid.UUID
    case_status: str
    cleared_by: uuid.UUID
    cleared_at: datetime


class SarReportBundleOut(BaseModel):
    """Pseudonymised NCA-style report bundle.

    Real names, IBANs, account numbers, and exact amounts are NEVER
    included — only pseudonymous references and banded values.
    """
    sar_case_id: uuid.UUID
    tenant_id: uuid.UUID
    payment_ref: str            # pseudonymised payment identifier
    beneficiary_ref: str        # pseudonymised — not the real name
    counterparty_ref: str       # pseudonymised counterparty identifier
    amount_band: str            # banded, not exact
    currency_code: str
    trigger_reasons: list[str]
    mlro_user_id: uuid.UUID
    decision_timestamp: str
    reported_at: str


# ────────────────────────────────── Endpoints ─────────────────────────────────


@router.get(
    "/queue",
    response_model=list[SarQueueItemOut],
    summary="List flagged payments awaiting MLRO review",
)
def sar_queue(actor: SarUser) -> list[SarQueueItemOut]:
    """Return all cases currently in UNDER_REVIEW state."""
    queue = _payments.sar_queue()
    result: list[SarQueueItemOut] = []
    for case in queue:
        payment_and_case = _payments.sar_case_by_id(case.sar_case_id)
        if payment_and_case is None:
            continue
        _, stored = payment_and_case
        result.append(
            SarQueueItemOut(
                sar_case_id=case.sar_case_id,
                queued_at=case.created_at,
                flag_count=len(case.flags),
                amount_band=_amount_band(stored.payload.amount),
                beneficiary_ref=_pseudo(stored.payload.beneficiary_name, "BEN"),
                currency_code=stored.payload.currency_code,
                case_status=case.status,
            )
        )
    return result


@router.get(
    "/{sar_id}",
    response_model=SarCaseOut,
    summary="Retrieve a single SAR case",
)
def sar_get(sar_id: uuid.UUID, actor: SarUser) -> SarCaseOut:
    """Retrieve full case detail for MLRO review."""
    pair = _payments.sar_case_by_id(sar_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="SAR case not found")
    case, _ = pair
    return SarCaseOut(
        sar_case_id=case.sar_case_id,
        queued_at=case.created_at,
        case_status=case.status,
        trigger_reasons=[f.flag for f in case.flags],
        trigger_details=[f.detail for f in case.flags],
        mlro_user_id=case.mlro_user_id,
    )


@router.post(
    "/{sar_id}/clear",
    response_model=SarClearOut,
    summary="MLRO clears the case — payment unfreezes and resumes normal workflow",
)
def sar_clear(sar_id: uuid.UUID, actor: SarUser) -> SarClearOut:
    """MLRO determines no reportable activity; payment is unfrozen."""
    pair = _payments.sar_case_by_id(sar_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="SAR case not found")
    case, _ = pair
    _payments.mlro_decision(case.payment_id, mlro_user_id=actor.user_id, decision="CLEAR")
    return SarClearOut(
        sar_case_id=sar_id,
        case_status="CLEARED",
        cleared_by=actor.user_id,
        cleared_at=datetime.now(tz=timezone.utc),
    )


@router.post(
    "/{sar_id}/report",
    response_model=SarReportBundleOut,
    summary="MLRO confirms SAR — generates pseudonymised report bundle, payment remains frozen",
)
def sar_report(sar_id: uuid.UUID, actor: SarUser) -> SarReportBundleOut:
    """MLRO confirms reportable activity.

    Calls mlro_decision(REPORT), then builds a pseudonymised bundle
    suitable for NCA submission.  The payment remains frozen.
    Real beneficiary names, IBANs, and account numbers are NEVER
    included in this response.
    """
    pair = _payments.sar_case_by_id(sar_id)
    if pair is None:
        raise HTTPException(status_code=404, detail="SAR case not found")
    case, stored = pair

    decision_ts = datetime.now(tz=timezone.utc)
    _payments.mlro_decision(case.payment_id, mlro_user_id=actor.user_id, decision="REPORT")

    return SarReportBundleOut(
        sar_case_id=sar_id,
        tenant_id=stored.payload.tenant_id,
        payment_ref=_pseudo(str(case.payment_id), "PAY"),
        beneficiary_ref=_pseudo(stored.payload.beneficiary_name, "BEN"),
        counterparty_ref=_pseudo(str(stored.payload.counterparty_id), "CTP"),
        amount_band=_amount_band(stored.payload.amount),
        currency_code=stored.payload.currency_code,
        trigger_reasons=[f.flag for f in case.flags],
        mlro_user_id=actor.user_id,
        decision_timestamp=decision_ts.isoformat(),
        reported_at=datetime.now(tz=timezone.utc).isoformat(),
    )
