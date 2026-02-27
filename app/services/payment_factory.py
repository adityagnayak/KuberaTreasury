"""
NexusTreasury — Payment Factory Service (Phase 3)
Four-Eyes approval, sanctions screening, PAIN.001 export.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, getcontext

# FIX: Added 'cast' to imports
from typing import List, Optional, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from lxml import etree
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InsufficientFundsError,
    InvalidBICError,
    InvalidIBANError,
    InvalidSignatureError,
    InvalidStateTransitionError,
    PaymentNotFoundError,
    PaymentValidationError,
    SanctionsHitError,
    SelfApprovalError,
)
from app.models.entities import BankAccount
from app.models.payments import Payment, PaymentAuditLog, SanctionsAlert
from app.models.transactions import CashPosition

getcontext().prec = 28


# ─── Payment State Machine ────────────────────────────────────────────────────

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"PENDING_APPROVAL"},
    "PENDING_APPROVAL": {"APPROVED", "REJECTED"},
    "APPROVED": {"SANCTIONS_REVIEW"},
    "SANCTIONS_REVIEW": {"FUNDS_CHECKED", "FROZEN"},
    "FUNDS_CHECKED": {"VALIDATED", "INSUFFICIENT_FUNDS"},
    "VALIDATED": {"EXPORTED", "FAILED_VALIDATION"},
    "EXPORTED": {"SETTLED"},
    "SETTLED": set(),
    "REJECTED": set(),
    "FROZEN": set(),
    "FAILED_VALIDATION": set(),
    "INSUFFICIENT_FUNDS": set(),
}


def advance_state(current: str, target: str) -> str:
    """Validate and advance the payment state machine."""
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidStateTransitionError(current, target)
    return target


# ─── Result types ─────────────────────────────────────────────────────────────


@dataclass
class PaymentRequest:
    debtor_account_id: str
    debtor_iban: str
    beneficiary_name: str
    beneficiary_bic: str
    beneficiary_iban: str
    beneficiary_country: str
    amount: Decimal
    currency: str
    execution_date: str
    remittance_info: Optional[str] = None
    end_to_end_id: Optional[str] = None


@dataclass
class ApprovalResult:
    payment_id: str
    checker_user_id: str
    status: str
    signature_fingerprint: str
    approved_at: datetime


@dataclass
class PAIN001Result:
    payment_id: str
    xml_bytes: bytes
    end_to_end_id: str
    status: str


# ─── IBAN / BIC validation ────────────────────────────────────────────────────

IBAN_LENGTHS: dict[str, int] = {
    "GB": 22,
    "DE": 22,
    "FR": 27,
    "NL": 18,
    "ES": 24,
    "IT": 27,
    "CH": 21,
    "AT": 20,
    "BE": 16,
    "SE": 24,
}
BIC_REGEX = re.compile(r"^[A-Z]{6}[A-Z2-9][A-NP-Z0-9]([A-Z0-9]{3})?$")


def _iban_mod97(iban: str) -> int:
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    return int(numeric) % 97


def validate_iban_field(iban: str) -> Optional[str]:
    iban = iban.replace(" ", "").upper()
    if len(iban) < 4:
        return "IBAN too short"
    if not iban[:2].isalpha():
        return "IBAN must start with 2-letter country code"
    expected = IBAN_LENGTHS.get(iban[:2])
    if expected and len(iban) != expected:
        return f"IBAN length {len(iban)} invalid for {iban[:2]} (expected {expected})"
    if _iban_mod97(iban) != 1:
        return "IBAN check digits failed MOD-97"
    return None


def validate_bic_field(bic: str) -> Optional[str]:
    if not BIC_REGEX.match(bic.upper()):
        return f"BIC '{bic}' does not match expected format"
    return None


# ─── RSA crypto helpers ───────────────────────────────────────────────────────


def generate_rsa_keypair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # FIX: Explicit cast ensures mypy knows this is RSAPublicKey
    return private_key, cast(RSAPublicKey, private_key.public_key())


def sign_approval(
    payment_id: str,
    amount: Decimal,
    timestamp: datetime,
    private_key: RSAPrivateKey,
) -> bytes:
    payload = f"{payment_id}|{amount}|{timestamp.isoformat()}".encode("utf-8")
    return private_key.sign(payload, padding.PKCS1v15(), hashes.SHA256())


def verify_approval_signature(
    payment_id: str,
    amount: Decimal,
    timestamp: datetime,
    signature_b64: str,
    public_key_pem: str,
) -> bool:
    public_key: RSAPublicKey = serialization.load_pem_public_key(
        public_key_pem.encode("utf-8")
    )
    payload = f"{payment_id}|{amount}|{timestamp.isoformat()}".encode("utf-8")
    sig_bytes = base64.b64decode(signature_b64)
    try:
        public_key.verify(sig_bytes, payload, padding.PKCS1v15(), hashes.SHA256())
        return True
    except InvalidSignature:
        raise InvalidSignatureError(payment_id)


def public_key_fingerprint(public_key: RSAPublicKey) -> str:
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def public_key_to_pem(public_key: RSAPublicKey) -> str:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


# ─── Sanctions Screening ──────────────────────────────────────────────────────

MOCK_OFAC_LIST: List[dict] = [
    {
        "name": "NEXUS_BLOCKED_CORP",
        "bic": "BLCKUS33XXX",
        "country": "IR",
        "list_type": "SDN",
    },
    {
        "name": "PHANTOM_TRADE_LTD",
        "bic": "PHNTGB2LXXX",
        "country": "KP",
        "list_type": "SDN",
    },
    {
        "name": "DARK_FINANCE_AG",
        "bic": "DRKNDE00XXX",
        "country": "SY",
        "list_type": "SDN",
    },
    {
        "name": "ROGUE_CAPITAL_PARTNERS",
        "bic": "ROGUUS44XXX",
        "country": "CU",
        "list_type": "NONSDN",
    },
    {
        "name": "SHADOW_BANK_INTL",
        "bic": "SHDWSG1XXXX",
        "country": "MM",
        "list_type": "SDN",
    },
    {
        "name": "Oleg Deripaska",
        "bic": "OLEGRU22XXX",
        "country": "RU",
        "list_type": "SDN",
    },
]


class SanctionsScreeningService:
    def __init__(
        self,
        ofac_list: Optional[List[dict]] = None,
        threshold: float = 0.85,
    ) -> None:
        self.ofac_list = ofac_list if ofac_list is not None else MOCK_OFAC_LIST
        self.threshold = threshold

    def screen(self, session: Session, payment: Payment) -> Optional[dict]:
        # 1. Exact BIC match
        for entry in self.ofac_list:
            if str(payment.beneficiary_bic).upper() == entry["bic"].upper():
                return self._record_hit(
                    session, payment, "bic", str(payment.beneficiary_bic), entry, 1.0
                )

        # 2. Exact country match
        for entry in self.ofac_list:
            if str(payment.beneficiary_country).upper() == entry["country"].upper():
                return self._record_hit(
                    session,
                    payment,
                    "country",
                    str(payment.beneficiary_country),
                    entry,
                    1.0,
                )

        # 3. Fuzzy name match
        for entry in self.ofac_list:
            score = difflib.SequenceMatcher(
                None,
                str(payment.beneficiary_name).upper(),
                entry["name"].upper(),
            ).ratio()
            if score >= self.threshold:
                return self._record_hit(
                    session,
                    payment,
                    "name",
                    str(payment.beneficiary_name),
                    entry,
                    score,
                )

        return None

    def _record_hit(
        self,
        session: Session,
        payment: Payment,
        matched_field: str,
        matched_value: str,
        entry: dict,
        score: float,
    ) -> dict:
        payment.status = "FROZEN"
        payment.updated_at = datetime.utcnow()

        alert = SanctionsAlert(
            payment_id=str(payment.id),
            matched_field=matched_field,
            matched_value=matched_value,
            list_entry_name=entry["name"],
            list_type=entry["list_type"],
            similarity_score=Decimal(str(round(score, 4))),
        )
        session.add(alert)
        session.flush()

        return {
            "payment_id": str(payment.id),
            "matched_field": matched_field,
            "matched_value": matched_value,
            "list_entry_name": entry["name"],
            "list_type": entry["list_type"],
            "similarity_score": score,
        }


# ─── PAIN.001 Validator ───────────────────────────────────────────────────────


class PAIN001Validator:
    REQUIRED_FIELDS = [
        "debtor_iban",
        "beneficiary_iban",
        "beneficiary_bic",
        "amount",
        "currency",
        "end_to_end_id",
        "execution_date",
    ]

    def validate(self, payment: Payment) -> List[dict]:
        errors: List[dict] = []

        for f in self.REQUIRED_FIELDS:
            val = getattr(payment, f, None)
            if val is None or str(val).strip() == "":
                errors.append(
                    {"field": f, "error": "Required field is missing or empty"}
                )

        for fname, iban_val in [
            ("debtor_iban", payment.debtor_iban),
            ("beneficiary_iban", payment.beneficiary_iban),
        ]:
            if iban_val:
                err = validate_iban_field(str(iban_val))
                if err:
                    errors.append({"field": fname, "error": err})

        if payment.beneficiary_bic:
            err = validate_bic_field(str(payment.beneficiary_bic))
            if err:
                errors.append({"field": "beneficiary_bic", "error": err})

        if payment.amount is not None:
            try:
                amt = Decimal(str(payment.amount))
                if amt <= 0:
                    errors.append(
                        {"field": "amount", "error": "Amount must be positive"}
                    )
            except Exception:
                errors.append(
                    {"field": "amount", "error": "Amount is not a valid decimal"}
                )

        if payment.execution_date:
            try:
                datetime.strptime(str(payment.execution_date), "%Y-%m-%d")
            except ValueError:
                errors.append(
                    {"field": "execution_date", "error": "Must be YYYY-MM-DD format"}
                )

        return errors


# ─── PAIN.001 XML Builder ─────────────────────────────────────────────────────

PAIN001_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"


def build_pain001_xml(payment: Payment) -> bytes:
    """Generate ISO 20022 PAIN.001.001.09 XML for a validated payment."""
    nsmap = {None: PAIN001_NS}
    doc = etree.Element("Document", nsmap=nsmap)
    cstmr = etree.SubElement(doc, "CstmrCdtTrfInitn")

    grp_hdr = etree.SubElement(cstmr, "GrpHdr")
    etree.SubElement(grp_hdr, "MsgId").text = f"NEXUS-{str(payment.id)[:8].upper()}"
    etree.SubElement(grp_hdr, "CreDtTm").text = datetime.utcnow().strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    etree.SubElement(grp_hdr, "NbOfTxs").text = "1"
    etree.SubElement(grp_hdr, "CtrlSum").text = str(
        Decimal(str(payment.amount)).quantize(Decimal("0.01"))
    )
    initg_pty = etree.SubElement(grp_hdr, "InitgPty")
    etree.SubElement(initg_pty, "Nm").text = "NexusTreasury"

    pmt_inf = etree.SubElement(cstmr, "PmtInf")
    etree.SubElement(pmt_inf, "PmtInfId").text = f"PMTINF-{str(payment.id)[:8].upper()}"
    etree.SubElement(pmt_inf, "PmtMtd").text = "TRF"
    etree.SubElement(pmt_inf, "NbOfTxs").text = "1"
    etree.SubElement(pmt_inf, "CtrlSum").text = str(
        Decimal(str(payment.amount)).quantize(Decimal("0.01"))
    )

    pmt_tp = etree.SubElement(pmt_inf, "PmtTpInf")
    svc_lvl = etree.SubElement(pmt_tp, "SvcLvl")
    etree.SubElement(svc_lvl, "Cd").text = "SEPA"

    etree.SubElement(pmt_inf, "ReqdExctnDt").text = str(payment.execution_date)

    dbtr = etree.SubElement(pmt_inf, "Dbtr")
    etree.SubElement(dbtr, "Nm").text = "NexusTreasury Debtor"
    dbtr_acct = etree.SubElement(pmt_inf, "DbtrAcct")
    dbtr_acct_id = etree.SubElement(dbtr_acct, "Id")
    etree.SubElement(dbtr_acct_id, "IBAN").text = str(payment.debtor_iban)

    dbtr_agt = etree.SubElement(pmt_inf, "DbtrAgt")
    fin_instn = etree.SubElement(dbtr_agt, "FinInstnId")
    etree.SubElement(fin_instn, "BICFI").text = "NEXUSGB2L"

    cdt_trf = etree.SubElement(pmt_inf, "CdtTrfTxInf")
    pmt_id = etree.SubElement(cdt_trf, "PmtId")
    etree.SubElement(pmt_id, "EndToEndId").text = str(payment.end_to_end_id)

    amt = etree.SubElement(cdt_trf, "Amt")
    instd_amt = etree.SubElement(amt, "InstdAmt", Ccy=str(payment.currency))
    instd_amt.text = str(Decimal(str(payment.amount)).quantize(Decimal("0.01")))

    cdtr_agt = etree.SubElement(cdt_trf, "CdtrAgt")
    cdtr_fin = etree.SubElement(cdtr_agt, "FinInstnId")
    etree.SubElement(cdtr_fin, "BICFI").text = str(payment.beneficiary_bic)

    cdtr = etree.SubElement(cdt_trf, "Cdtr")
    etree.SubElement(cdtr, "Nm").text = str(payment.beneficiary_name)

    cdtr_acct = etree.SubElement(cdt_trf, "CdtrAcct")
    cdtr_acct_id = etree.SubElement(cdtr_acct, "Id")
    etree.SubElement(cdtr_acct_id, "IBAN").text = str(payment.beneficiary_iban)

    if payment.remittance_info:
        rmt_inf = etree.SubElement(cdt_trf, "RmtInf")
        etree.SubElement(rmt_inf, "Ustrd").text = str(payment.remittance_info)

    return etree.tostring(
        doc, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


# ─── Payment Service ──────────────────────────────────────────────────────────


class PaymentService:
    def __init__(
        self,
        session: Session,
        sanctions_service: Optional[SanctionsScreeningService] = None,
    ) -> None:
        self.session = session
        self.sanctions = sanctions_service or SanctionsScreeningService()
        self.validator = PAIN001Validator()

    def initiate_payment(
        self, payment_req: PaymentRequest, maker_user_id: str
    ) -> Payment:
        # 1. Immediate Validation
        for iban, fname in [
            (payment_req.debtor_iban, "debtor_iban"),
            (payment_req.beneficiary_iban, "beneficiary_iban"),
        ]:
            if validate_iban_field(iban):
                raise InvalidIBANError(iban)

        if validate_bic_field(payment_req.beneficiary_bic):
            raise InvalidBICError(payment_req.beneficiary_bic)

        account = (
            self.session.query(BankAccount)
            .filter_by(id=payment_req.debtor_account_id)
            .first()
        )
        if account:
            cash_pos = (
                self.session.query(CashPosition)
                .filter_by(account_id=account.id)
                .order_by(CashPosition.position_date.desc())
                .first()
            )
            current_balance = (
                Decimal(str(cash_pos.value_date_balance)) if cash_pos else Decimal("0")
            )
            available = current_balance + Decimal(str(account.overdraft_limit))
            if payment_req.amount > available:
                raise InsufficientFundsError(
                    available=available, requested=payment_req.amount
                )

        # 2. Generate ID and Create Payment (DRAFT)
        new_payment_id = str(uuid.uuid4())
        e2e_id = payment_req.end_to_end_id or f"E2E-{uuid.uuid4().hex[:16].upper()}"

        payment = Payment(
            id=new_payment_id,
            maker_user_id=maker_user_id,
            debtor_account_id=payment_req.debtor_account_id,
            debtor_iban=payment_req.debtor_iban,
            beneficiary_name=payment_req.beneficiary_name,
            beneficiary_bic=payment_req.beneficiary_bic,
            beneficiary_iban=payment_req.beneficiary_iban,
            beneficiary_country=payment_req.beneficiary_country,
            amount=payment_req.amount,
            currency=payment_req.currency,
            end_to_end_id=e2e_id,
            execution_date=payment_req.execution_date,
            remittance_info=payment_req.remittance_info,
            status="DRAFT",
        )

        # Add to session immediately so it's available for foreign key checks
        self.session.add(payment)

        # 3. Immediate Sanctions Screening
        hit = self.sanctions.screen(self.session, payment)
        if hit:
            self._audit(str(payment.id), "SYSTEM", "SANCTIONS_HIT", str(hit))
            self.session.commit()
            raise SanctionsHitError(
                payment_id=hit["payment_id"],
                matched_field=hit["matched_field"],
                matched_value=hit["matched_value"],
                list_entry_name=hit["list_entry_name"],
                list_type=hit["list_type"],
                similarity_score=hit["similarity_score"],
            )

        # 4. If no hit, proceed to pending approval
        self.session.flush()
        payment.status = advance_state("DRAFT", "PENDING_APPROVAL")
        payment.updated_at = datetime.utcnow()
        self._audit(str(payment.id), maker_user_id, "PAYMENT_INITIATED")
        self.session.commit()
        return payment

    def approve_payment(
        self,
        payment_id: str,
        checker_user_id: str,
        private_key: RSAPrivateKey,
    ) -> ApprovalResult:
        payment = self._get_payment(payment_id)

        # EDGE CASE: Self-approval hard block
        if checker_user_id == payment.maker_user_id:
            self._audit(payment_id, checker_user_id, "SELF_APPROVAL_ATTEMPT")
            self.session.commit()
            raise SelfApprovalError(checker_user_id)

        if str(payment.status) != "PENDING_APPROVAL":
            raise InvalidStateTransitionError(str(payment.status), "APPROVED")

        approval_ts = datetime.utcnow()
        sig_bytes = sign_approval(
            payment_id, Decimal(str(payment.amount)), approval_ts, private_key
        )
        sig_b64 = base64.b64encode(sig_bytes).decode("utf-8")
        pub_key = private_key.public_key()
        fingerprint = public_key_fingerprint(pub_key)
        pub_pem = public_key_to_pem(pub_key)

        payment.checker_user_id = checker_user_id
        payment.approval_signature = sig_b64
        payment.approval_public_key_pem = pub_pem
        payment.approval_public_key_fingerprint = fingerprint
        payment.approval_timestamp = approval_ts
        payment.status = advance_state("PENDING_APPROVAL", "APPROVED")
        payment.status = advance_state("APPROVED", "SANCTIONS_REVIEW")
        payment.updated_at = datetime.utcnow()

        hit = self.sanctions.screen(self.session, payment)
        if hit:
            self._audit(
                payment_id,
                "SYSTEM",
                "SANCTIONS_HIT",
                f"field={hit['matched_field']} entry={hit['list_entry_name']}",
            )
            self.session.commit()
            raise SanctionsHitError(
                payment_id=hit["payment_id"],
                matched_field=hit["matched_field"],
                matched_value=hit["matched_value"],
                list_entry_name=hit["list_entry_name"],
                list_type=hit["list_type"],
                similarity_score=hit["similarity_score"],
            )

        payment.status = advance_state("SANCTIONS_REVIEW", "FUNDS_CHECKED")
        payment.updated_at = 