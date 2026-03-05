from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from statistics import mean, pstdev
from typing import Callable, Literal
from xml.etree import ElementTree as ET

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, field_validator
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PaymentState = Literal[
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "REJECTED",
    "EXPORTED",
    "CONFIRMED",
    "RECONCILED",
]
RoleName = Literal[
    "treasury_analyst",
    "treasury_manager",
    "cfo",
    "head_of_treasury",
    "board_member",
    "compliance_officer",
    "auditor",
]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _round_2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _sim_score(left: str, right: str) -> Decimal:
    return Decimal(
        str(round(SequenceMatcher(None, left.lower(), right.lower()).ratio() * 100, 2))
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_round_over_50k(amount: Decimal) -> bool:
    return amount >= Decimal("50000") and amount == amount.quantize(Decimal("1"))


class ApprovalTier(BaseModel):
    min_amount: Decimal = Field(ge=Decimal("0"))
    max_amount: Decimal | None = None
    initiator_role: RoleName
    approver_roles: list[RoleName]

    @field_validator("approver_roles")
    @classmethod
    def non_empty(cls, v: list[RoleName]) -> list[RoleName]:
        if not v:
            raise ValueError("approver_roles must not be empty")
        return v


class ApprovalMatrix(BaseModel):
    tiers: list[ApprovalTier]
    non_gbp_extra_approver_role: RoleName = "head_of_treasury"
    enhanced_due_diligence_role: RoleName = "compliance_officer"


class MandateCheckLog(BaseModel):
    timestamp: datetime
    source: Literal["companies_house", "hmrc_vat"]
    result: Literal["pass", "fail"]
    match_score: Decimal
    action: str


class ScreeningLog(BaseModel):
    timestamp: datetime
    payment_id: uuid.UUID
    beneficiary_name: str
    sanctions_entity: str
    match_score: Decimal
    threshold_hit: bool


class SarFlag(BaseModel):
    flag: str
    detail: str


class SarCase(BaseModel):
    sar_case_id: uuid.UUID
    tenant_id: uuid.UUID
    payment_id: uuid.UUID
    flags: list[SarFlag]
    status: Literal["UNDER_REVIEW", "CLEARED", "REPORTED"]
    created_at: datetime
    mlro_user_id: uuid.UUID | None = None
    report_payload: dict[str, str] | None = None


class PaymentInstructionIn(BaseModel):
    tenant_id: uuid.UUID
    payment_batch_id: uuid.UUID | None = None
    initiator_user_id: uuid.UUID
    initiator_role: RoleName
    debit_bank_account_id: uuid.UUID
    counterparty_id: uuid.UUID
    beneficiary_name: str
    amount: Decimal = Field(gt=Decimal("0"))
    currency_code: str = Field(min_length=3, max_length=3)
    scheduled_for: datetime
    urgent: bool = False
    same_day: bool = False
    available_balance: Decimal
    overdraft_limit: Decimal = Decimal("0")
    min_buffer: Decimal = Decimal("0")
    destination_country_code: str = Field(min_length=2, max_length=2)
    ip_address: str | None = None
    hmrc_tax_type: Literal["CT", "VAT", "PAYE", "CIS"] | None = None
    hmrc_payment_reference: str | None = None
    company_number: str | None = None
    vat_number: str | None = None
    registered_company_name: str | None = None


class ApprovalDecisionIn(BaseModel):
    payment_id: uuid.UUID
    approver_user_id: uuid.UUID
    approver_role: RoleName
    decision: Literal["approved", "rejected"]
    reason: str | None = None


class PaymentApprovalRecord(BaseModel):
    approver_user_id: uuid.UUID
    approver_role: RoleName
    decision: Literal["approved", "rejected"]
    reason: str | None = None
    decided_at: datetime


class PaymentInstructionOut(BaseModel):
    payment_id: uuid.UUID
    tenant_id: uuid.UUID
    status: PaymentState
    frozen: bool
    under_review: bool
    route: Literal["BACS", "CHAPS", "FASTER_PAYMENTS"]
    enhanced_due_diligence_required: bool
    compliance_alerted: bool
    required_approver_roles: list[RoleName]
    approvals: list[PaymentApprovalRecord]
    duplicate_detected: bool
    sanctions_match_score: Decimal
    mandate_checks: list[MandateCheckLog]
    audit_trail: list[dict[str, str]]


class Pain001BatchRequest(BaseModel):
    tenant_id: uuid.UUID
    batch_id: uuid.UUID
    debtor_name: str
    debtor_iban: str
    debtor_bic: str
    payment_ids: list[uuid.UUID]
    requested_by_user_id: uuid.UUID


class Pain001BatchResponse(BaseModel):
    payment_batch_id: uuid.UUID
    generated_at: datetime
    file_name: str
    xml_content: str
    sha256_checksum: str


class MtdOauthTokenRequest(BaseModel):
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    authorization_code: str


class MtdTokenEnvelope(BaseModel):
    tenant_id: uuid.UUID
    encrypted_token: str
    encrypted_refresh_token: str
    nonce: str
    stored_at: datetime


class MtdApiAudit(BaseModel):
    endpoint: str
    response_code: int
    correlation_id: str | None
    timestamp: datetime
    user_id: uuid.UUID


class MtdVatReturnBuildRequest(BaseModel):
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    period_key: str
    rows: list[dict[str, str | Decimal]]


class MtdVatReturnBuildResponse(BaseModel):
    period_key: str
    box_1: Decimal
    box_2: Decimal
    box_3: Decimal
    box_4: Decimal
    box_5: Decimal
    box_6: Decimal
    box_7: Decimal
    box_8: Decimal
    box_9: Decimal
    requires_cfo_review: bool = True


class RegulatoryExportRequest(BaseModel):
    tenant_id: uuid.UUID
    operator_user_id: uuid.UUID
    from_ts: datetime
    to_ts: datetime
    journal_entries: list[dict[str, str]]
    payment_audit_trail: list[dict[str, str]]
    user_activity: list[dict[str, str]]
    ai_inference_log: list[dict[str, str]]
    sar_activity: list[dict[str, str]] = Field(default_factory=list)
    include_sar_activity: bool = False
    requester_role: RoleName


class RegulatoryExportBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, ser_json_bytes="base64")

    export_id: str
    generated_at: datetime
    pdf_bytes: bytes
    excel_bytes: bytes
    json_bytes: bytes
    digital_signature: str


class SignatureVerificationRequest(BaseModel):
    tenant_id: uuid.UUID
    pdf_bytes: bytes
    generated_at: datetime
    signature: str


class SignatureVerificationResponse(BaseModel):
    valid: bool


@dataclass
class _StoredPayment:
    payment_id: uuid.UUID
    payload: PaymentInstructionIn
    status: PaymentState
    frozen: bool
    under_review: bool
    required_approver_roles: list[RoleName]
    approvals: list[PaymentApprovalRecord]
    duplicate_detected: bool
    sanctions_match_score: Decimal
    mandate_checks: list[MandateCheckLog]
    compliance_alerted: bool
    enhanced_due_diligence_required: bool
    route: Literal["BACS", "CHAPS", "FASTER_PAYMENTS"]
    audit_trail: list[dict[str, str]]


class PaymentsComplianceService:
    def __init__(self) -> None:
        self._approval_matrices: dict[uuid.UUID, ApprovalMatrix] = {}
        self._payments: dict[uuid.UUID, _StoredPayment] = {}
        self._screening_logs: list[ScreeningLog] = []
        self._sar_cases: dict[uuid.UUID, SarCase] = {}
        self._verified_counterparties: set[tuple[uuid.UUID, uuid.UUID]] = set()
        self._fatf_high_risk = {"IR", "KP", "MM"}
        self._sanctions_entities = [
            "Bank Melli Iran",
            "Islamic Revolutionary Guard Corps",
            "National Iranian Oil Company",
            "Syrian Arab Airlines",
            "Belarusian State Security Committee",
        ]

    def configure_approval_matrix(
        self, tenant_id: uuid.UUID, matrix: ApprovalMatrix | None = None
    ) -> ApprovalMatrix:
        if matrix is None:
            matrix = ApprovalMatrix(
                tiers=[
                    ApprovalTier(
                        min_amount=Decimal("0"),
                        max_amount=Decimal("10000"),
                        initiator_role="treasury_analyst",
                        approver_roles=["treasury_manager"],
                    ),
                    ApprovalTier(
                        min_amount=Decimal("10000"),
                        max_amount=Decimal("100000"),
                        initiator_role="treasury_manager",
                        approver_roles=["cfo"],
                    ),
                    ApprovalTier(
                        min_amount=Decimal("100000"),
                        max_amount=Decimal("500000"),
                        initiator_role="cfo",
                        approver_roles=["head_of_treasury"],
                    ),
                    ApprovalTier(
                        min_amount=Decimal("500000"),
                        max_amount=None,
                        initiator_role="cfo",
                        approver_roles=["head_of_treasury", "board_member"],
                    ),
                ],
                non_gbp_extra_approver_role="head_of_treasury",
                enhanced_due_diligence_role="compliance_officer",
            )
        self._approval_matrices[tenant_id] = matrix
        return matrix

    def _matrix_for(self, tenant_id: uuid.UUID) -> ApprovalMatrix:
        if tenant_id not in self._approval_matrices:
            return self.configure_approval_matrix(tenant_id)
        return self._approval_matrices[tenant_id]

    def _tier_for_amount(self, matrix: ApprovalMatrix, amount: Decimal) -> ApprovalTier:
        for tier in matrix.tiers:
            if amount >= tier.min_amount and (
                tier.max_amount is None or amount < tier.max_amount
            ):
                return tier
        return matrix.tiers[-1]

    def _validate_hmrc_reference(self, tax_type: str | None, value: str | None) -> None:
        if not tax_type:
            return
        if not value:
            raise ValueError(
                "hmrc_payment_reference required when hmrc_tax_type is set"
            )
        if tax_type == "CT" and not (
            len(value) == 14 and value[:10].isdigit() and value.endswith("A001")
        ):
            raise ValueError("CT reference must be 10-digit UTR + A001")
        if tax_type == "VAT" and not (len(value) == 9 and value.isdigit()):
            raise ValueError("VAT reference must be 9-digit VRN")
        if tax_type == "PAYE" and len(value) != 13:
            raise ValueError("PAYE reference must be 13 characters")
        if tax_type == "CIS" and not value[:10].isdigit():
            raise ValueError("CIS reference must be UTR-based")

    def _funds_check(self, payload: PaymentInstructionIn) -> None:
        available = payload.available_balance + payload.overdraft_limit
        if available <= payload.amount + payload.min_buffer:
            raise ValueError("Insufficient funds with required minimum buffer")

    def _detect_duplicate(self, payload: PaymentInstructionIn) -> bool:
        for existing in self._payments.values():
            same_counterparty = (
                existing.payload.counterparty_id == payload.counterparty_id
            )
            same_amount = existing.payload.amount == payload.amount
            date_diff = abs(
                (existing.payload.scheduled_for - payload.scheduled_for).total_seconds()
            )
            if same_counterparty and same_amount and date_diff <= 86400:
                return True
        return False

    def _route_for(
        self, amount: Decimal, urgent: bool, same_day: bool
    ) -> Literal["BACS", "CHAPS", "FASTER_PAYMENTS"]:
        if urgent or same_day:
            return "CHAPS" if amount >= Decimal("100000") else "FASTER_PAYMENTS"
        if amount >= Decimal("250000"):
            return "CHAPS"
        if amount <= Decimal("250000"):
            return "FASTER_PAYMENTS"
        return "BACS"

    def _screen_sanctions(
        self, payment_id: uuid.UUID, beneficiary_name: str
    ) -> tuple[Decimal, bool]:
        top = Decimal("0")
        hit = False
        for entity in self._sanctions_entities:
            score = _sim_score(beneficiary_name, entity)
            if score > top:
                top = score
            threshold_hit = score >= Decimal("85")
            if score >= Decimal("60"):
                self._screening_logs.append(
                    ScreeningLog(
                        timestamp=_now(),
                        payment_id=payment_id,
                        beneficiary_name=beneficiary_name,
                        sanctions_entity=entity,
                        match_score=score,
                        threshold_hit=threshold_hit,
                    )
                )
            if threshold_hit:
                hit = True
        return top, hit

    def _build_required_roles(
        self,
        payload: PaymentInstructionIn,
        matrix: ApprovalMatrix,
        tier: ApprovalTier,
        first_payment: bool,
    ) -> list[RoleName]:
        required = list(tier.approver_roles)
        if payload.currency_code.upper() != "GBP":
            required.append(matrix.non_gbp_extra_approver_role)
        if payload.urgent or payload.same_day:
            required.append("cfo")
        if first_payment:
            required.append(matrix.enhanced_due_diligence_role)
        dedup: list[RoleName] = []
        for role in required:
            if role not in dedup:
                dedup.append(role)
        return dedup

    def _mandate_check_companies_house(
        self, payload: PaymentInstructionIn
    ) -> MandateCheckLog:
        if not payload.registered_company_name:
            return MandateCheckLog(
                timestamp=_now(),
                source="companies_house",
                result="fail",
                match_score=Decimal("0"),
                action="block_missing_registered_name",
            )

        status = "active"
        found_name = payload.registered_company_name
        if payload.company_number and payload.company_number.endswith("D"):
            status = "dissolved"
        score = _sim_score(payload.beneficiary_name, found_name)
        if status != "active" or score < Decimal("85"):
            return MandateCheckLog(
                timestamp=_now(),
                source="companies_house",
                result="fail",
                match_score=score,
                action="block_and_alert_compliance",
            )
        return MandateCheckLog(
            timestamp=_now(),
            source="companies_house",
            result="pass",
            match_score=score,
            action="allow",
        )

    def _mandate_check_hmrc_vat(self, payload: PaymentInstructionIn) -> MandateCheckLog:
        if not payload.vat_number:
            return MandateCheckLog(
                timestamp=_now(),
                source="hmrc_vat",
                result="fail",
                match_score=Decimal("0"),
                action="block_missing_vat",
            )
        score = _sim_score(
            payload.beneficiary_name,
            payload.registered_company_name or payload.beneficiary_name,
        )
        if (
            len(payload.vat_number) != 9
            or not payload.vat_number.isdigit()
            or score < Decimal("85")
        ):
            return MandateCheckLog(
                timestamp=_now(),
                source="hmrc_vat",
                result="fail",
                match_score=score,
                action="block_and_alert_compliance",
            )
        return MandateCheckLog(
            timestamp=_now(),
            source="hmrc_vat",
            result="pass",
            match_score=score,
            action="allow",
        )

    def _sar_flags(
        self, payload: PaymentInstructionIn, sanctions_score: Decimal
    ) -> list[SarFlag]:
        flags: list[SarFlag] = []
        historical_same_beneficiary = [
            p.payload.amount
            for p in self._payments.values()
            if p.payload.counterparty_id == payload.counterparty_id
        ]
        if len(historical_same_beneficiary) >= 2:
            avg = Decimal(str(mean([float(x) for x in historical_same_beneficiary])))
            sigma = Decimal(
                str(pstdev([float(x) for x in historical_same_beneficiary]))
            )
            if sigma > 0 and payload.amount > avg + (Decimal("3") * sigma):
                flags.append(
                    SarFlag(
                        flag="unusual_pattern", detail=">3 SD above historical range"
                    )
                )

        if payload.destination_country_code.upper() in self._fatf_high_risk:
            flags.append(
                SarFlag(
                    flag="high_risk_jurisdiction",
                    detail=payload.destination_country_code.upper(),
                )
            )

        near_threshold = [Decimal("10000"), Decimal("100000"), Decimal("500000")]
        for th in near_threshold:
            if payload.amount >= (th - Decimal("250")) and payload.amount < th:
                same_day_count = sum(
                    1
                    for p in self._payments.values()
                    if p.payload.counterparty_id == payload.counterparty_id
                    and p.payload.scheduled_for.date() == payload.scheduled_for.date()
                    and p.payload.amount >= (th - Decimal("250"))
                    and p.payload.amount < th
                )
                if same_day_count >= 1:
                    flags.append(
                        SarFlag(
                            flag="structuring_behaviour", detail=f"multiple near {th}"
                        )
                    )
                    break

        if sanctions_score >= Decimal("60"):
            flags.append(
                SarFlag(
                    flag="sanctioned_entity_proximity",
                    detail=f"score={sanctions_score}",
                )
            )

        if _is_round_over_50k(payload.amount):
            flags.append(
                SarFlag(flag="round_number_anomaly", detail="exact round > 50k")
            )

        return flags

    def initiate_payment(self, payload: PaymentInstructionIn) -> PaymentInstructionOut:
        matrix = self._matrix_for(payload.tenant_id)
        tier = self._tier_for_amount(matrix, payload.amount)
        if (
            payload.initiator_role != tier.initiator_role
            and payload.initiator_role != "cfo"
        ):
            raise ValueError("initiator role is not permitted for this amount tier")

        self._validate_hmrc_reference(
            payload.hmrc_tax_type, payload.hmrc_payment_reference
        )
        self._funds_check(payload)

        payment_id = uuid.uuid4()
        duplicate_detected = self._detect_duplicate(payload)

        first_payment = (
            payload.tenant_id,
            payload.counterparty_id,
        ) not in self._verified_counterparties
        required_roles = self._build_required_roles(
            payload, matrix, tier, first_payment=first_payment
        )

        mandate_logs: list[MandateCheckLog] = []
        compliance_alerted = False
        if first_payment:
            ch = self._mandate_check_companies_house(payload)
            vat = self._mandate_check_hmrc_vat(payload)
            mandate_logs = [ch, vat]
            if ch.result == "fail" or vat.result == "fail":
                compliance_alerted = True

        sanctions_score, sanctions_hit = self._screen_sanctions(
            payment_id, payload.beneficiary_name
        )
        frozen = sanctions_hit or compliance_alerted
        under_review = frozen

        sar_flags = self._sar_flags(payload, sanctions_score)
        if sar_flags:
            frozen = True
            under_review = True
            self._sar_cases[payment_id] = SarCase(
                sar_case_id=uuid.uuid4(),
                tenant_id=payload.tenant_id,
                payment_id=payment_id,
                flags=sar_flags,
                status="UNDER_REVIEW",
                created_at=_now(),
            )
            compliance_alerted = True

        status: PaymentState = "PENDING_APPROVAL"
        if compliance_alerted and (not sanctions_hit and not sar_flags):
            status = "REJECTED"

        route = self._route_for(payload.amount, payload.urgent, payload.same_day)
        audit_trail = [
            {
                "event": "created",
                "timestamp": _now().isoformat(),
                "actor_user_id": str(payload.initiator_user_id),
                "ip_address": payload.ip_address or "unknown",
            }
        ]

        stored = _StoredPayment(
            payment_id=payment_id,
            payload=payload,
            status=status,
            frozen=frozen,
            under_review=under_review,
            required_approver_roles=required_roles,
            approvals=[],
            duplicate_detected=duplicate_detected,
            sanctions_match_score=sanctions_score,
            mandate_checks=mandate_logs,
            compliance_alerted=compliance_alerted,
            enhanced_due_diligence_required=first_payment,
            route=route,
            audit_trail=audit_trail,
        )
        self._payments[payment_id] = stored

        if all(log.result == "pass" for log in mandate_logs) and first_payment:
            self._verified_counterparties.add(
                (payload.tenant_id, payload.counterparty_id)
            )

        return self._to_response(stored)

    def approve_payment(self, payload: ApprovalDecisionIn) -> PaymentInstructionOut:
        if payload.payment_id not in self._payments:
            raise ValueError("payment not found")
        payment = self._payments[payload.payment_id]

        if payment.payload.initiator_user_id == payload.approver_user_id:
            raise ValueError("four-eyes control: initiator cannot approve")

        if payment.under_review and payload.approver_role != "compliance_officer":
            raise ValueError("payment is under review")

        if (
            payload.approver_role not in payment.required_approver_roles
            and payload.decision == "approved"
        ):
            raise ValueError("approver role not required for this payment")

        decision_record = PaymentApprovalRecord(
            approver_user_id=payload.approver_user_id,
            approver_role=payload.approver_role,
            decision=payload.decision,
            reason=payload.reason,
            decided_at=_now(),
        )
        payment.approvals.append(decision_record)
        payment.audit_trail.append(
            {
                "event": f"approval_{payload.decision}",
                "timestamp": _now().isoformat(),
                "actor_user_id": str(payload.approver_user_id),
                "ip_address": payment.payload.ip_address or "unknown",
            }
        )

        if payload.decision == "rejected":
            payment.status = "REJECTED"
            return self._to_response(payment)

        approved_roles = {
            a.approver_role for a in payment.approvals if a.decision == "approved"
        }
        if all(role in approved_roles for role in payment.required_approver_roles):
            payment.status = "APPROVED"

        return self._to_response(payment)

    def export_pain001_batch(
        self, payload: Pain001BatchRequest
    ) -> Pain001BatchResponse:
        exportable: list[_StoredPayment] = []
        for pid in payload.payment_ids:
            payment = self._payments.get(pid)
            if payment is None:
                raise ValueError("payment not found")
            if payment.status != "APPROVED" or payment.frozen:
                raise ValueError(
                    "all payments must be approved and unfrozen before export"
                )
            exportable.append(payment)

        doc = ET.Element(
            "Document",
            attrib={"xmlns": "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"},
        )
        cstmr = ET.SubElement(doc, "CstmrCdtTrfInitn")
        grp = ET.SubElement(cstmr, "GrpHdr")
        ET.SubElement(grp, "MsgId").text = str(payload.batch_id)
        ET.SubElement(grp, "CreDtTm").text = _now().isoformat()
        ET.SubElement(grp, "NbOfTxs").text = str(len(exportable))
        ET.SubElement(grp, "CtrlSum").text = str(
            _round_2(sum((p.payload.amount for p in exportable), Decimal("0")))
        )

        for payment in exportable:
            pmt_inf = ET.SubElement(cstmr, "PmtInf")
            ET.SubElement(pmt_inf, "PmtInfId").text = str(payment.payment_id)
            ET.SubElement(pmt_inf, "PmtMtd").text = "TRF"
            ET.SubElement(pmt_inf, "ReqdExctnDt").text = (
                payment.payload.scheduled_for.date().isoformat()
            )
            dbtr = ET.SubElement(pmt_inf, "Dbtr")
            ET.SubElement(dbtr, "Nm").text = payload.debtor_name
            dbtr_acct = ET.SubElement(pmt_inf, "DbtrAcct")
            dbtr_id = ET.SubElement(dbtr_acct, "Id")
            ET.SubElement(dbtr_id, "IBAN").text = payload.debtor_iban
            dbtr_agt = ET.SubElement(pmt_inf, "DbtrAgt")
            fin = ET.SubElement(dbtr_agt, "FinInstnId")
            ET.SubElement(fin, "BICFI").text = payload.debtor_bic

            tx = ET.SubElement(pmt_inf, "CdtTrfTxInf")
            pmt_id = ET.SubElement(tx, "PmtId")
            ET.SubElement(pmt_id, "EndToEndId").text = str(payment.payment_id)
            amt = ET.SubElement(tx, "Amt")
            ET.SubElement(
                amt, "InstdAmt", attrib={"Ccy": payment.payload.currency_code.upper()}
            ).text = str(_round_2(payment.payload.amount))
            cdtr = ET.SubElement(tx, "Cdtr")
            ET.SubElement(cdtr, "Nm").text = payment.payload.beneficiary_name
            rmt = ET.SubElement(tx, "RmtInf")
            ET.SubElement(rmt, "Ustrd").text = (
                payment.payload.hmrc_payment_reference or "MANUAL_UPLOAD"
            )

            payment.status = "EXPORTED"
            payment.audit_trail.append(
                {
                    "event": "exported",
                    "timestamp": _now().isoformat(),
                    "actor_user_id": str(payload.requested_by_user_id),
                    "ip_address": payment.payload.ip_address or "unknown",
                }
            )

        xml_content = ET.tostring(doc, encoding="utf-8", xml_declaration=True).decode(
            "utf-8"
        )
        checksum = _hash(xml_content)
        file_name = f"pain001_{payload.batch_id}.xml"
        return Pain001BatchResponse(
            payment_batch_id=payload.batch_id,
            generated_at=_now(),
            file_name=file_name,
            xml_content=xml_content,
            sha256_checksum=checksum,
        )

    def confirm_payment(
        self, payment_id: uuid.UUID, actor_user_id: uuid.UUID
    ) -> PaymentInstructionOut:
        payment = self._payments[payment_id]
        payment.status = "CONFIRMED"
        payment.audit_trail.append(
            {
                "event": "confirmed",
                "timestamp": _now().isoformat(),
                "actor_user_id": str(actor_user_id),
                "ip_address": payment.payload.ip_address or "unknown",
            }
        )
        return self._to_response(payment)

    def reconcile_payment(
        self, payment_id: uuid.UUID, actor_user_id: uuid.UUID
    ) -> PaymentInstructionOut:
        payment = self._payments[payment_id]
        payment.status = "RECONCILED"
        payment.audit_trail.append(
            {
                "event": "reconciled",
                "timestamp": _now().isoformat(),
                "actor_user_id": str(actor_user_id),
                "ip_address": payment.payload.ip_address or "unknown",
            }
        )
        return self._to_response(payment)

    def mlro_decision(
        self,
        payment_id: uuid.UUID,
        *,
        mlro_user_id: uuid.UUID,
        decision: Literal["CLEAR", "REPORT"],
    ) -> PaymentInstructionOut:
        payment = self._payments[payment_id]
        case = self._sar_cases.get(payment_id)
        if case is None:
            raise ValueError("no SAR case exists")

        case.mlro_user_id = mlro_user_id
        if decision == "CLEAR":
            case.status = "CLEARED"
            payment.frozen = False
            payment.under_review = False
            if payment.status == "PENDING_APPROVAL":
                approved_roles = {
                    a.approver_role
                    for a in payment.approvals
                    if a.decision == "approved"
                }
                if all(
                    role in approved_roles for role in payment.required_approver_roles
                ):
                    payment.status = "APPROVED"
        else:
            case.status = "REPORTED"
            case.report_payload = {
                "format": "NCA_goAML",
                "payment_id": str(payment_id),
                "decision": "REPORT",
                "timestamp": _now().isoformat(),
            }
            payment.frozen = True
            payment.under_review = True

        return self._to_response(payment)

    def sar_case_view(
        self, payment_id: uuid.UUID, requester_role: RoleName
    ) -> dict[str, str]:
        case = self._sar_cases.get(payment_id)
        if case is None:
            return {"status": "none"}
        if requester_role != "compliance_officer":
            return {"status": "under review"}
        return {
            "status": case.status,
            "sar_case_id": str(case.sar_case_id),
            "flags": "; ".join(f.flag for f in case.flags),
        }

    def sar_queue(self) -> list[SarCase]:
        """Return all SAR cases currently awaiting MLRO review (UNDER_REVIEW).

        Only the MLRO / compliance_officer should ever receive the output of
        this method.  No external caller should pass this data to non-MLRO
        roles.
        """
        return [
            case
            for case in self._sar_cases.values()
            if case.status == "UNDER_REVIEW"
        ]

    def sar_case_by_id(self, sar_case_id: uuid.UUID) -> tuple[SarCase, _StoredPayment] | None:
        """Look up a SAR case and its associated payment by sar_case_id."""
        for payment_id, case in self._sar_cases.items():
            if case.sar_case_id == sar_case_id:
                payment = self._payments.get(payment_id)
                if payment:
                    return case, payment
        return None

    def _to_response(self, payment: _StoredPayment) -> PaymentInstructionOut:
        return PaymentInstructionOut(
            payment_id=payment.payment_id,
            tenant_id=payment.payload.tenant_id,
            status=payment.status,
            frozen=payment.frozen,
            under_review=payment.under_review,
            route=payment.route,
            enhanced_due_diligence_required=payment.enhanced_due_diligence_required,
            compliance_alerted=payment.compliance_alerted,
            required_approver_roles=payment.required_approver_roles,
            approvals=payment.approvals,
            duplicate_detected=payment.duplicate_detected,
            sanctions_match_score=payment.sanctions_match_score,
            mandate_checks=payment.mandate_checks,
            audit_trail=payment.audit_trail,
        )


class HmrcMtdService:
    def __init__(self) -> None:
        self._token_store: dict[uuid.UUID, MtdTokenEnvelope] = {}
        self._audit_log: list[MtdApiAudit] = []

    def _sandbox_base(self) -> str:
        return "https://test-api.service.hmrc.gov.uk"

    def _prod_base(self) -> str:
        return os.getenv("HMRC_API_BASE_URL", "https://api.service.hmrc.gov.uk")

    def _base_url(self) -> str:
        sandbox_mode = os.getenv("HMRC_SANDBOX_MODE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return self._sandbox_base() if sandbox_mode else self._prod_base()

    def _encryption_key(self) -> bytes:
        key_hex = os.getenv("HMRC_TOKEN_ENCRYPTION_KEY")
        if not key_hex:
            key_hex = os.getenv("MFA_TOTP_ENCRYPTION_KEY")
        if not key_hex:
            raise ValueError(
                "HMRC_TOKEN_ENCRYPTION_KEY (or MFA_TOTP_ENCRYPTION_KEY) must be configured"
            )
        raw = bytes.fromhex(key_hex)
        if len(raw) != 32:
            raise ValueError("Token encryption key must be 32 bytes (64 hex chars)")
        return raw

    def _encrypt(self, value: str) -> tuple[str, str]:
        aes = AESGCM(self._encryption_key())
        nonce = os.urandom(12)
        cipher = aes.encrypt(nonce, value.encode("utf-8"), None)
        return base64.b64encode(cipher).decode("utf-8"), base64.b64encode(nonce).decode(
            "utf-8"
        )

    def _decrypt(self, value_b64: str, nonce_b64: str) -> str:
        aes = AESGCM(self._encryption_key())
        plain = aes.decrypt(
            base64.b64decode(nonce_b64), base64.b64decode(value_b64), None
        )
        return plain.decode("utf-8")

    def store_oauth_tokens(
        self, tenant_id: uuid.UUID, access_token: str, refresh_token: str
    ) -> MtdTokenEnvelope:
        enc_access, nonce = self._encrypt(access_token)
        enc_refresh, _ = self._encrypt(refresh_token)
        envelope = MtdTokenEnvelope(
            tenant_id=tenant_id,
            encrypted_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            nonce=nonce,
            stored_at=_now(),
        )
        self._token_store[tenant_id] = envelope
        return envelope

    def _auth_header(self, tenant_id: uuid.UUID) -> dict[str, str]:
        env = self._token_store.get(tenant_id)
        if env is None:
            return {}
        return {
            "Authorization": f"Bearer {self._decrypt(env.encrypted_token, env.nonce)}"
        }

    def _request(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        method: str,
        endpoint: str,
        payload: dict | None = None,
    ) -> dict:
        base = self._base_url()
        if "test-api.service.hmrc.gov.uk" in base and os.getenv(
            "HMRC_SANDBOX_MODE", "true"
        ).lower() not in {"true", "1", "yes", "on"}:
            raise ValueError("UAT must use HMRC sandbox endpoint")

        url = f"{base}{endpoint}"
        headers = {
            "Accept": "application/vnd.hmrc.1.0+json",
            **self._auth_header(tenant_id),
        }
        with httpx.Client(timeout=20.0) as client:
            response = client.request(
                method=method, url=url, json=payload, headers=headers
            )

        corr = response.headers.get("CorrelationId") or response.headers.get(
            "X-Correlation-Id"
        )
        self._audit_log.append(
            MtdApiAudit(
                endpoint=endpoint,
                response_code=response.status_code,
                correlation_id=corr,
                timestamp=_now(),
                user_id=user_id,
            )
        )
        body = response.json() if response.content else {}
        if response.status_code >= 400:
            raise ValueError(f"HMRC API error {response.status_code}: {body}")
        return body

    def obligations(self, tenant_id: uuid.UUID, user_id: uuid.UUID, vrn: str) -> dict:
        return self._request(
            tenant_id, user_id, "GET", f"/organisations/vat/{vrn}/obligations"
        )

    def submit_return(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, vrn: str, payload: dict
    ) -> dict:
        return self._request(
            tenant_id,
            user_id,
            "POST",
            f"/organisations/vat/{vrn}/returns",
            payload=payload,
        )

    def get_return(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, vrn: str, period_key: str
    ) -> dict:
        return self._request(
            tenant_id, user_id, "GET", f"/organisations/vat/{vrn}/returns/{period_key}"
        )

    def liabilities(self, tenant_id: uuid.UUID, user_id: uuid.UUID, vrn: str) -> dict:
        return self._request(
            tenant_id, user_id, "GET", f"/organisations/vat/{vrn}/liabilities"
        )

    def payments(self, tenant_id: uuid.UUID, user_id: uuid.UUID, vrn: str) -> dict:
        return self._request(
            tenant_id, user_id, "GET", f"/organisations/vat/{vrn}/payments"
        )

    def build_vat_return(
        self, payload: MtdVatReturnBuildRequest
    ) -> MtdVatReturnBuildResponse:
        box_1 = Decimal("0")
        box_4 = Decimal("0")
        box_6 = Decimal("0")
        box_7 = Decimal("0")

        for row in payload.rows:
            vat_treatment = str(row.get("vat_treatment", ""))
            net = Decimal(str(row.get("net_amount", "0")))
            vat = Decimal(str(row.get("vat_amount", "0")))
            if vat_treatment in {"T0", "T1"}:
                if vat >= 0:
                    box_1 += vat
                else:
                    box_4 += abs(vat)
                if net >= 0:
                    box_6 += net
                else:
                    box_7 += abs(net)

        box_1 = _round_2(box_1)
        box_2 = Decimal("0.00")
        box_3 = _round_2(box_1 + box_2)
        box_4 = _round_2(box_4)
        box_5 = _round_2(box_3 - box_4)
        box_6 = _round_2(box_6)
        box_7 = _round_2(box_7)
        box_8 = Decimal("0.00")
        box_9 = Decimal("0.00")

        return MtdVatReturnBuildResponse(
            period_key=payload.period_key,
            box_1=box_1,
            box_2=box_2,
            box_3=box_3,
            box_4=box_4,
            box_5=box_5,
            box_6=box_6,
            box_7=box_7,
            box_8=box_8,
            box_9=box_9,
            requires_cfo_review=True,
        )

    def audit_log(self) -> list[MtdApiAudit]:
        return list(self._audit_log)


class RegulatoryExportService:
    def __init__(self) -> None:
        self._history: list[dict[str, str]] = []

    def generate_bundle(
        self, payload: RegulatoryExportRequest
    ) -> RegulatoryExportBundle:
        if (
            payload.include_sar_activity
            and payload.requester_role != "compliance_officer"
        ):
            raise ValueError("SAR activity export is MLRO-only")

        export_id = str(uuid.uuid4())
        generated_at = _now()

        body = {
            "journal_entries": payload.journal_entries,
            "payment_audit_trail": payload.payment_audit_trail,
            "user_activity": payload.user_activity,
            "ai_inference_log": payload.ai_inference_log,
            "sar_activity": (
                payload.sar_activity if payload.include_sar_activity else []
            ),
        }

        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)
        c.setTitle("KuberaTreasury Regulatory Export")
        c.drawString(50, 800, "KuberaTreasury Regulatory Export")
        c.drawString(50, 785, f"Export ID: {export_id}")
        c.drawString(50, 770, f"Generated: {generated_at.isoformat()}")
        c.drawString(50, 755, f"Tenant: {payload.tenant_id}")
        c.drawString(50, 740, f"Journal entries: {len(payload.journal_entries)}")
        c.drawString(50, 725, f"Payments: {len(payload.payment_audit_trail)}")
        c.drawString(50, 710, f"User activity: {len(payload.user_activity)}")
        c.drawString(50, 695, f"AI logs: {len(payload.ai_inference_log)}")
        c.drawString(50, 680, f"SAR activity included: {payload.include_sar_activity}")
        c.showPage()
        c.save()
        pdf_bytes = pdf_buffer.getvalue()

        excel_lines = [
            "section,count",
            f"journal_entries,{len(payload.journal_entries)}",
            f"payment_audit_trail,{len(payload.payment_audit_trail)}",
            f"user_activity,{len(payload.user_activity)}",
            f"ai_inference_log,{len(payload.ai_inference_log)}",
            f"sar_activity,{len(payload.sar_activity) if payload.include_sar_activity else 0}",
        ]
        excel_bytes = "\n".join(excel_lines).encode("utf-8")
        json_bytes = json.dumps(body, default=str).encode("utf-8")

        signature = _hash(
            pdf_bytes.hex() + generated_at.isoformat() + str(payload.tenant_id)
        )
        self._history.append(
            {
                "export_id": export_id,
                "tenant_id": str(payload.tenant_id),
                "generated_at": generated_at.isoformat(),
                "signature": signature,
            }
        )

        return RegulatoryExportBundle(
            export_id=export_id,
            generated_at=generated_at,
            pdf_bytes=pdf_bytes,
            excel_bytes=excel_bytes,
            json_bytes=json_bytes,
            digital_signature=signature,
        )

    def verify_signature(
        self, payload: SignatureVerificationRequest
    ) -> SignatureVerificationResponse:
        expected = _hash(
            payload.pdf_bytes.hex()
            + payload.generated_at.isoformat()
            + str(payload.tenant_id)
        )
        return SignatureVerificationResponse(valid=(expected == payload.signature))

    def retention_alerts(self, records: list[dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        now = _now().date()
        for record in records:
            created = date.fromisoformat(record["created_date"])
            retention_years = int(record["retention_years"])
            age_days = (now - created).days
            if retention_years == 7 and age_days >= (6 * 365):
                out.append(
                    {"record_id": record["record_id"], "action": "review_at_year_6"}
                )
            if age_days >= retention_years * 365:
                out.append(
                    {"record_id": record["record_id"], "action": "retention_due"}
                )
        return out
