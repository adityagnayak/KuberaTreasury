"""
NexusTreasury — ORM Models: Payments & Sanctions Alerts (Phase 3)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Enum, ForeignKey,
    Numeric, String, Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Payment(Base):
    """Payment instruction with Four-Eyes approval and PAIN.001 export."""

    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Maker (initiator)
    maker_user_id = Column(String(255), nullable=False)
    # Checker (approver) — set on approval
    checker_user_id = Column(String(255), nullable=True)

    # Debtor (our side)
    debtor_account_id = Column(
        String(36), ForeignKey("bank_accounts.id"), nullable=False
    )
    debtor_iban = Column(String(34), nullable=False)

    # Creditor (beneficiary)
    beneficiary_name = Column(String(255), nullable=False)
    beneficiary_bic = Column(String(11), nullable=False)
    beneficiary_iban = Column(String(34), nullable=False)
    beneficiary_country = Column(String(2), nullable=False)

    amount = Column(Numeric(precision=28, scale=8), nullable=False)
    currency = Column(String(3), nullable=False)
    end_to_end_id = Column(String(35), nullable=False, unique=True)
    execution_date = Column(String(10), nullable=False)   # ISO date string YYYY-MM-DD
    remittance_info = Column(Text, nullable=True)

    status = Column(String(30), nullable=False, default="DRAFT")

    # Cryptographic approval
    approval_signature = Column(Text, nullable=True)           # base64 RSA-SHA256
    approval_public_key_pem = Column(Text, nullable=True)
    approval_public_key_fingerprint = Column(String(64), nullable=True)
    approval_timestamp = Column(DateTime, nullable=True)

    # Generated PAIN.001 XML
    pain001_xml = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "checker_user_id IS NULL OR checker_user_id != maker_user_id",
            name="ck_payments_no_self_approval",
        ),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )

    debtor_account = relationship("BankAccount", back_populates="payments")
    sanctions_alerts = relationship("SanctionsAlert", back_populates="payment")


class SanctionsAlert(Base):
    """Records a sanctions list hit for a specific payment."""

    __tablename__ = "sanctions_alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payment_id = Column(String(36), ForeignKey("payments.id"), nullable=False)
    matched_field = Column(String(50), nullable=False)   # 'name' | 'bic' | 'country'
    matched_value = Column(String(255), nullable=False)
    list_entry_name = Column(String(255), nullable=False)
    list_type = Column(String(10), nullable=False)       # SDN | NONSDN
    similarity_score = Column(Numeric(precision=5, scale=4), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    payment = relationship("Payment", back_populates="sanctions_alerts")


class PaymentAuditLog(Base):
    """Payment-specific audit log entries."""

    __tablename__ = "payment_audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payment_id = Column(String(36), ForeignKey("payments.id"), nullable=True)
    user_id = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    payment = relationship("Payment")
