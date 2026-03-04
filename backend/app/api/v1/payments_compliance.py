from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.services.payments_compliance_service import (
    ApprovalDecisionIn,
    ApprovalMatrix,
    HmrcMtdService,
    MtdApiAudit,
    MtdVatReturnBuildRequest,
    MtdVatReturnBuildResponse,
    Pain001BatchRequest,
    Pain001BatchResponse,
    PaymentInstructionIn,
    PaymentInstructionOut,
    PaymentsComplianceService,
    RegulatoryExportBundle,
    RegulatoryExportRequest,
    RegulatoryExportService,
    SignatureVerificationRequest,
    SignatureVerificationResponse,
)

router = APIRouter(prefix="/payments", tags=["Payments"])

_payments = PaymentsComplianceService()
_hmrc = HmrcMtdService()
_exports = RegulatoryExportService()


@router.post("/approval-matrix/{tenant_id}", response_model=ApprovalMatrix, summary="Configure tenant approval matrix")
async def configure_matrix(tenant_id: uuid.UUID, payload: ApprovalMatrix | None = None) -> ApprovalMatrix:
    return _payments.configure_approval_matrix(tenant_id=tenant_id, matrix=payload)


@router.post("/initiate", response_model=PaymentInstructionOut, summary="Initiate payment with compliance controls")
async def initiate_payment(payload: PaymentInstructionIn) -> PaymentInstructionOut:
    return _payments.initiate_payment(payload)


@router.post("/approve", response_model=PaymentInstructionOut, summary="Approve or reject payment")
async def approve_payment(payload: ApprovalDecisionIn) -> PaymentInstructionOut:
    return _payments.approve_payment(payload)


@router.post("/batch/pain001", response_model=Pain001BatchResponse, summary="Generate PAIN.001 XML for manual upload")
async def export_pain001(payload: Pain001BatchRequest) -> Pain001BatchResponse:
    return _payments.export_pain001_batch(payload)


@router.post("/{payment_id}/confirm", response_model=PaymentInstructionOut, summary="Mark payment as confirmed")
async def confirm_payment(payment_id: uuid.UUID, actor_user_id: uuid.UUID) -> PaymentInstructionOut:
    return _payments.confirm_payment(payment_id=payment_id, actor_user_id=actor_user_id)


@router.post("/{payment_id}/reconcile", response_model=PaymentInstructionOut, summary="Mark payment as reconciled")
async def reconcile_payment(payment_id: uuid.UUID, actor_user_id: uuid.UUID) -> PaymentInstructionOut:
    return _payments.reconcile_payment(payment_id=payment_id, actor_user_id=actor_user_id)


@router.post("/{payment_id}/sar/clear", response_model=PaymentInstructionOut, summary="MLRO clears SAR review")
async def sar_clear(payment_id: uuid.UUID, mlro_user_id: uuid.UUID) -> PaymentInstructionOut:
    return _payments.mlro_decision(payment_id, mlro_user_id=mlro_user_id, decision="CLEAR")


@router.post("/{payment_id}/sar/report", response_model=PaymentInstructionOut, summary="MLRO files SAR and keeps freeze")
async def sar_report(payment_id: uuid.UUID, mlro_user_id: uuid.UUID) -> PaymentInstructionOut:
    return _payments.mlro_decision(payment_id, mlro_user_id=mlro_user_id, decision="REPORT")


@router.get("/{payment_id}/sar/view", response_model=dict[str, str], summary="SAR workspace view")
async def sar_view(payment_id: uuid.UUID, requester_role: str) -> dict[str, str]:
    return _payments.sar_case_view(payment_id, requester_role=requester_role)  # type: ignore[arg-type]


@router.post("/hmrc/mtd/tokens", summary="Store HMRC OAuth tokens encrypted")
async def hmrc_store_tokens(tenant_id: uuid.UUID, access_token: str, refresh_token: str) -> dict:
    envelope = _hmrc.store_oauth_tokens(tenant_id, access_token, refresh_token)
    return envelope.model_dump()


@router.get("/hmrc/mtd/{vrn}/obligations", summary="HMRC MTD VAT obligations")
async def hmrc_obligations(vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    return _hmrc.obligations(tenant_id=tenant_id, user_id=user_id, vrn=vrn)


@router.post("/hmrc/mtd/{vrn}/returns", summary="HMRC MTD VAT submit return")
async def hmrc_submit_return(vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID, payload: dict) -> dict:
    return _hmrc.submit_return(tenant_id=tenant_id, user_id=user_id, vrn=vrn, payload=payload)


@router.get("/hmrc/mtd/{vrn}/returns/{period_key}", summary="HMRC MTD VAT get return")
async def hmrc_get_return(vrn: str, period_key: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    return _hmrc.get_return(tenant_id=tenant_id, user_id=user_id, vrn=vrn, period_key=period_key)


@router.get("/hmrc/mtd/{vrn}/liabilities", summary="HMRC MTD VAT liabilities")
async def hmrc_liabilities(vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    return _hmrc.liabilities(tenant_id=tenant_id, user_id=user_id, vrn=vrn)


@router.get("/hmrc/mtd/{vrn}/payments", summary="HMRC MTD VAT payments")
async def hmrc_payments(vrn: str, tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    return _hmrc.payments(tenant_id=tenant_id, user_id=user_id, vrn=vrn)


@router.post("/hmrc/mtd/vat-return-builder", response_model=MtdVatReturnBuildResponse, summary="Build VAT return boxes 1-9")
async def hmrc_vat_return_builder(payload: MtdVatReturnBuildRequest) -> MtdVatReturnBuildResponse:
    return _hmrc.build_vat_return(payload)


@router.get("/hmrc/mtd/audit-log", response_model=list[MtdApiAudit], summary="HMRC MTD API call audit")
async def hmrc_audit_log() -> list[MtdApiAudit]:
    return _hmrc.audit_log()


@router.post("/regulatory-export", response_model=RegulatoryExportBundle, summary="Export PDF/Excel/JSON bundle")
async def regulatory_export(payload: RegulatoryExportRequest) -> RegulatoryExportBundle:
    return _exports.generate_bundle(payload)


@router.post("/regulatory-export/verify", response_model=SignatureVerificationResponse, summary="Verify export signature")
async def verify_export_signature(payload: SignatureVerificationRequest) -> SignatureVerificationResponse:
    return _exports.verify_signature(payload)


@router.post("/retention/alerts", response_model=list[dict[str, str]], summary="Retention policy alerts")
async def retention_alerts(records: list[dict[str, str]]) -> list[dict[str, str]]:
    return _exports.retention_alerts(records)
