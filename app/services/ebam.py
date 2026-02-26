"""
NexusTreasury — E-BAM (Electronic Bank Account Management) Service (Phase 5)
Mandate lifecycle management, KYC document tracking, expiration alerting.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ExpiredMandateError,
    MandateKeyMismatchError,
    NoMandateError,
)
from app.models.entities import BankAccount
from app.models.mandates import KYCDocument, Mandate
from app.models.transactions import AuditLog


@dataclass
class ExpirationAlert:
    item_type: str  # "mandate" | "kyc_document"
    item_id: str
    owner_id: str
    expires_on: date
    days_remaining: int
    detail: str


class EBAMService:
    """Manages mandates and KYC document lifecycle."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ── Mandate management ────────────────────────────────────────────────────

    def create_mandate(
        self,
        account_id: str,
        signatory_name: str,
        signatory_user_id: str,
        public_key: RSAPublicKey,
        valid_from: date,
        valid_until: date,
    ) -> Mandate:
        pub_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        mandate = Mandate(
            account_id=account_id,
            signatory_name=signatory_name,
            signatory_user_id=signatory_user_id,
            public_key_pem=pub_pem,
            valid_from=valid_from,
            valid_until=valid_until,
            status="active",
        )
        self.session.add(mandate)
        self.session.commit()
        return mandate

    def revoke_mandate(self, mandate_id: str, revoking_user_id: str) -> Mandate:
        m = self.session.query(Mandate).filter_by(id=mandate_id).first()
        if m is None:
            raise ValueError(f"Mandate {mandate_id} not found")
        m.status = "revoked"
        self._log(mandate_id, revoking_user_id, "MANDATE_REVOKED")
        self.session.commit()
        return m

    def get_active_mandates(self, account_id: str) -> List[Mandate]:
        today = date.today()
        return (
            self.session.query(Mandate)
            .filter(
                Mandate.account_id == account_id,
                Mandate.status == "active",
                Mandate.valid_from <= today,
                Mandate.valid_until >= today,
            )
            .all()
        )

    def validate_payment_mandate(
        self,
        account_id: str,
        checker_public_key_pem: Optional[str] = None,
    ) -> Mandate:
        """
        Enforce E-BAM rules before PAIN.001 export:
        - NoMandateError     → no mandate row at all
        - ExpiredMandateError → mandate exists but expired
        - MandateKeyMismatchError → checker key not in active mandates
        """
        today = date.today()
        all_mandates = (
            self.session.query(Mandate)
            .filter_by(account_id=account_id)
            .order_by(Mandate.valid_until.desc())
            .all()
        )
        if not all_mandates:
            raise NoMandateError(account_id)

        active = [
            m
            for m in all_mandates
            if m.status == "active" and m.valid_from <= today <= m.valid_until
        ]
        if not active:
            expired = sorted(all_mandates, key=lambda m: m.valid_until, reverse=True)[0]
            acct = self.session.query(BankAccount).filter_by(id=account_id).first()
            if acct:
                acct.account_status = "expired_mandate"
            self._log(
                account_id,
                "SYSTEM",
                "EXPIRED_MANDATE_BLOCKED",
                f"expired_on={expired.valid_until.isoformat()}",
            )
            self.session.commit()
            raise ExpiredMandateError(account_id, expired.valid_until)

        if checker_public_key_pem:
            match = any(
                m.public_key_pem.strip() == checker_public_key_pem.strip()
                for m in active
            )
            if not match:
                raise MandateKeyMismatchError(account_id)

        return active[0]

    # ── KYC documents ─────────────────────────────────────────────────────────

    def register_kyc_document(
        self,
        entity_id: str,
        doc_type: str,
        doc_bytes: bytes,
        expiry_date: Optional[date] = None,
    ) -> KYCDocument:
        doc_hash = hashlib.sha256(doc_bytes).hexdigest()
        doc = KYCDocument(
            entity_id=entity_id,
            doc_type=doc_type,
            doc_hash=doc_hash,
            expiry_date=expiry_date,
        )
        self.session.add(doc)
        self.session.commit()
        return doc

    # ── Expiration alerting ───────────────────────────────────────────────────

    def check_upcoming_expirations(self, days_ahead: int = 30) -> List[ExpirationAlert]:
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)
        alerts: List[ExpirationAlert] = []

        # Mandates
        mandates = (
            self.session.query(Mandate)
            .filter(
                Mandate.status == "active",
                Mandate.valid_until >= today,
                Mandate.valid_until <= cutoff,
            )
            .all()
        )
        for m in mandates:
            alerts.append(
                ExpirationAlert(
                    item_type="mandate",
                    item_id=m.id,
                    owner_id=m.account_id,
                    expires_on=m.valid_until,
                    days_remaining=(m.valid_until - today).days,
                    detail=f"Signatory: {m.signatory_name}",
                )
            )

        # KYC documents
        kyc_docs = (
            self.session.query(KYCDocument)
            .filter(
                KYCDocument.expiry_date.isnot(None),
                KYCDocument.expiry_date >= today,
                KYCDocument.expiry_date <= cutoff,
            )
            .all()
        )
        for d in kyc_docs:
            alerts.append(
                ExpirationAlert(
                    item_type="kyc_document",
                    item_id=d.id,
                    owner_id=d.entity_id,
                    expires_on=d.expiry_date,
                    days_remaining=(d.expiry_date - today).days,
                    detail=f"Doc type: {d.doc_type}",
                )
            )

        return alerts

    # ── Private ───────────────────────────────────────────────────────────────

    def _log(
        self, record_id: str, user_id: str, action: str, details: str = ""
    ) -> None:
        log = AuditLog(
            table_name="mandates",
            record_id=record_id,
            action="UPDATE",
            new_value=json.dumps({"action": action, "details": details}),
            user_id=user_id,
        )
        self.session.add(log)
        self.session.flush()
