from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import AuthUser, DBSession
from app.services.beneficiary_verify import (
    BeneficiaryVerifyRequest,
    BeneficiaryVerifyResult,
    BeneficiaryVerifyService,
    log_verification,
)
from app.services.payments_compliance_service import (
    ApprovalDecisionIn,
    ApprovalMatrix,
    HmrcMtdService,
    MandateCheckLog,
    MtdApiAudit,
    MtdVatReturnBuildRequest,
    MtdVatReturnBuildResponse,
    Pain001BatchRequest,
    Pain001BatchResponse,
    PaymentApprovalRecord,
    PaymentInstructionIn,
    PaymentInstructionOut,
    PaymentsComplianceService,
    RegulatoryExportBundle,
    RegulatoryExportRequest,
    RegulatoryExportService,
    RoleName,
    SignatureVerificationRequest,
    SignatureVerificationResponse,
)

# ── Tipping-off-safe public response schema ────────────────────────────────────
# POCA 2002 s.333A: the words "SAR", "suspicious", and "money laundering" must
# never appear in a payments-router response.  Internal investigation fields
# (frozen, under_review, compliance_alerted, sanctions_match_score) are
# stripped; a payment under MLRO review is presented as "UNDER_REVIEW".


class PaymentPublicOut(BaseModel):
    """Payments-router response — no internal review state is exposed."""

    payment_id: uuid.UUID
    tenant_id: uuid.UUID
    status: str  # "UNDER_REVIEW" when internally frozen/under_review
    route: Literal["BACS", "CHAPS", "FASTER_PAYMENTS"]
    enhanced_due_diligence_required: bool
    required_approver_roles: list[RoleName]
    approvals: list[PaymentApprovalRecord]
    duplicate_detected: bool
    mandate_checks: list[MandateCheckLog]
    audit_trail: list[dict[str, str]]
    # Fields intentionally omitted from this schema:
    #   frozen, under_review, compliance_alerted, sanctions_match_score


def _to_public(out: PaymentInstructionOut) -> PaymentPublicOut:
    """Convert internal response to the tipping-off-safe public schema."""
    public_status = (
        "UNDER_REVIEW" if (out.frozen or out.under_review) else out.status
    )
    return PaymentPublicOut(
        payment_id=out.payment_id,
        tenant_id=out.tenant_id,
        status=public_status,
        route=out.route,
        enhanced_due_diligence_required=out.enhanced_due_diligence_required,
        required_approver_roles=out.required_approver_roles,
        approvals=out.approvals,
        duplicate_detected=out.duplicate_detected,
        mandate_checks=out.mandate_checks,
        audit_trail=out.audit_trail,
    )

router = APIRouter(prefix="/payments", tags=["Payments"])

_payments = PaymentsComplianceService()
_hmrc = HmrcMtdService()
_exports = RegulatoryExportService()
_verify = BeneficiaryVerifyService()


@router.post(
    "/approval-matrix/{tenant_id}",
    response_model=ApprovalMatrix,
    summary="Configure tenant approval matrix",
)
async def configure_matrix(
    tenant_id: uuid.UUID, payload: ApprovalMatrix | None = None
) -> ApprovalMatrix:
    return _payments.configure_approval_matrix(tenant_id=tenant_id, matrix=payload)


@router.post(
    "/initiate",
    response_model=PaymentPublicOut,
    summary="Initiate payment with compliance controls",
)
async def initiate_payment(payload: PaymentInstructionIn) -> PaymentPublicOut:
    return _to_public(_payments.initiate_payment(payload))


@router.post(
    "/approve",
    response_model=PaymentPublicOut,
    summary="Approve or reject payment",
)
async def approve_payment(payload: ApprovalDecisionIn) -> PaymentPublicOut:
    return _to_public(_payments.approve_payment(payload))


@router.post(
    "/batch/pain001",
    response_model=Pain001BatchResponse,
    summary="Generate PAIN.001 XML for manual upload",
)
async def export_pain001(payload: Pain001BatchRequest) -> Pain001BatchResponse:
    return _payments.export_pain001_batch(payload)


@router.post(
    "/{payment_id}/confirm",
    response_model=PaymentPublicOut,
    summary="Mark payment as confirmed",
)
async def confirm_payment(
    payment_id: uuid.UUID, actor_user_id: uuid.UUID
) -> PaymentPublicOut:
    return _to_public(_payments.confirm_payment(payment_id=payment_id, actor_user_id=actor_user_id))


@router.post(
    "/{payment_id}/reconcile",
    response_model=PaymentPublicOut,
    summary="Mark payment as reconciled",
)
async def reconcile_payment(
    payment_id: uuid.UUID, actor_user_id: uuid.UUID
) -> PaymentPublicOut:
    return _to_public(
        _payments.reconcile_payment(payment_id=payment_id, actor_user_id=actor_user_id)
    )


@router.post("/hmrc/mtd/tokens", summary="Store HMRC OAuth tokens encrypted")
async def hmrc_store_tokens(
    tenant_id: uuid.UUID, access_token: str, refresh_token: str
) -> dict:
    envelope = _hmrc.store_oauth_tokens(tenant_id, access_token, refresh_token)
    return envelope.model_dump()


@router.get("/hmrc/mtd/{vrn}/obligations", summary="HMRC MTD VAT obligations")
async def hmrc_obligations(vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    return _hmrc.obligations(tenant_id=tenant_id, user_id=user_id, vrn=vrn)


@router.post("/hmrc/mtd/{vrn}/returns", summary="HMRC MTD VAT submit return")
async def hmrc_submit_return(
    vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: dict
) -> dict:
    return _hmrc.submit_return(
        tenant_id=tenant_id, user_id=user_id, vrn=vrn, payload=payload
    )


@router.get("/hmrc/mtd/{vrn}/returns/{period_key}", summary="HMRC MTD VAT get return")
async def hmrc_get_return(
    vrn: str, period_key: str, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> dict:
    return _hmrc.get_return(
        tenant_id=tenant_id, user_id=user_id, vrn=vrn, period_key=period_key
    )


@router.get("/hmrc/mtd/{vrn}/liabilities", summary="HMRC MTD VAT liabilities")
async def hmrc_liabilities(vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    return _hmrc.liabilities(tenant_id=tenant_id, user_id=user_id, vrn=vrn)


@router.get("/hmrc/mtd/{vrn}/payments", summary="HMRC MTD VAT payments")
async def hmrc_payments(vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    return _hmrc.payments(tenant_id=tenant_id, user_id=user_id, vrn=vrn)


@router.post(
    "/hmrc/mtd/vat-return-builder",
    response_model=MtdVatReturnBuildResponse,
    summary="Build VAT return boxes 1-9",
)
async def hmrc_vat_return_builder(
    payload: MtdVatReturnBuildRequest,
) -> MtdVatReturnBuildResponse:
    return _hmrc.build_vat_return(payload)


@router.get(
    "/hmrc/mtd/audit-log",
    response_model=list[MtdApiAudit],
    summary="HMRC MTD API call audit",
)
async def hmrc_audit_log() -> list[MtdApiAudit]:
    return _hmrc.audit_log()


@router.post(
    "/regulatory-export",
    response_model=RegulatoryExportBundle,
    summary="Export PDF/Excel/JSON bundle",
)
async def regulatory_export(payload: RegulatoryExportRequest) -> RegulatoryExportBundle:
    return _exports.generate_bundle(payload)


@router.post(
    "/regulatory-export/verify",
    response_model=SignatureVerificationResponse,
    summary="Verify export signature",
)
async def verify_export_signature(
    payload: SignatureVerificationRequest,
) -> SignatureVerificationResponse:
    return _exports.verify_signature(payload)


@router.post(
    "/retention/alerts",
    response_model=list[dict[str, str]],
    summary="Retention policy alerts",
)
async def retention_alerts(records: list[dict[str, str]]) -> list[dict[str, str]]:
    return _exports.retention_alerts(records)


@router.post(
    "/beneficiaries/verify",
    response_model=BeneficiaryVerifyResult,
    summary="Verify a new payment beneficiary (Companies House + HMRC VAT)",
    description=(
        "Runs Companies House name-match and HMRC VAT checks before the first "
        "payment to a beneficiary can be approved. Results are cached for 24 h. "
        "Requires at minimum the **treasury_analyst** role."
    ),
)
async def verify_beneficiary(
    payload: BeneficiaryVerifyRequest,
    db: DBSession,
    actor: AuthUser,
) -> BeneficiaryVerifyResult:
    """Verify a beneficiary via Companies House and HMRC VAT."""
    _ALLOWED_ROLES = {"treasury_analyst", "treasury_manager", "cfo",
                     "head_of_treasury", "compliance_officer", "system_admin"}
    if not _ALLOWED_ROLES.intersection(set(actor.roles)):
        raise HTTPException(status_code=403, detail="Forbidden: treasury_analyst role required")

    result = _verify.verify(payload)
    await log_verification(db, payload, result)
    return result
