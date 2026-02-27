"""
NexusTreasury — ORM Models: Payments & Sanctions Alerts (Phase 3)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.entities import BankAccount


class Payment(Base):
    """Payment instruction with Four-Eyes approval and PAIN.001 export."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Maker (initiator)
    maker_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Checker (approver) — set on approval
    checker_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Debtor (our side)
    debtor_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("bank_accounts.id"), nullable=False
    )
    debtor_iban: Mapped[str] = mapped_column(String(34), nullable=False)

    # Creditor (beneficiary)
    beneficiary_name: Mapped[str] = mapped_column(String(255), nullable=False)
    beneficiary_bic: Mapped[str] = mapped_column(String(11), nullable=False)
    beneficiary_iban: Mapped[str] = mapped_column(String(34), nullable=False)
    beneficiary_country: Mapped[str] = mapped_column(String(2), nullable=False)

    amount: Mapped[Decimal] = mapped_column(Numeric(precision=28, scale=8), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    end_to_end_id: Mapped[str] = mapped_column(String(35), nullable=False, unique=True)
    execution_date: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO date string YYYY-MM-DD
    remittance_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")

    # Cryptographic approval
    approval_signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # base64 RSA-SHA256
    approval_public_key_pem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_public_key_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approval_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Generated PAIN.001 XML
    pain001_xml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "checker_user_id IS NULL OR checker_user_id != maker_user_id",
            name="ck_payments_no_self_approval",
        ),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )

    debtor_account: Mapped["BankAccount"] = relationship("BankAccount", back_populates="payments")
    sanctions_alerts: Mapped[List["SanctionsAlert"]] = relationship("SanctionsAlert", back_populates="payment")


class SanctionsAlert(Base):
    """Records a sanctions list hit for a specific payment."""

    __tablename__ = "sanctions_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payment_id: Mapped[str] = mapped_column(String(36), ForeignKey("payments.id"), nullable=False)
    matched_field: Mapped[str] = mapped_column(String(50), nullable=False)  # 'name' | 'bic' | 'country'
    matched_value: Mapped[str] = mapped_column(String(255), nullable=False)
    list_entry_name: Mapped[str] = mapped_column(String(255), nullable=False)
    list_type: Mapped[str] = mapped_column(String(10), nullable=False)  # SDN | NONSDN
    similarity_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(precision=5, scale=4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    payment: Mapped["Payment"] = relationship("Payment", back_populates="sanctions_alerts")


class PaymentAuditLog(Base):
    """Payment-specific audit log entries."""

    __tablename__ = "payment_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payment_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("payments.id"), nullable=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    payment: Mapped["Payment"] = relationship("Payment")
