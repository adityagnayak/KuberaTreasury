"""
NexusTreasury — E-BAM Models (Phase 5)
Bank Mandates and Signatory Management.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Mandate(Base):
    """
    Represents authority to sign payments on a specific account.
    """

    __tablename__ = "mandates"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(String, ForeignKey("bank_accounts.id"), nullable=False)

    signatory_name: Mapped[str] = mapped_column(String, nullable=False)
    signatory_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Link to IAM user

    status: Mapped[str] = mapped_column(
        Enum("active", "revoked", "expired", name="mandate_status_enum"),
        default="active",
        nullable=False,
    )

    role: Mapped[Optional[str]] = mapped_column(String)  # e.g., "A-Signatory", "B-Signatory"
    limit_currency: Mapped[Optional[str]] = mapped_column(String(3))
    single_payment_limit: Mapped[Optional[str]] = mapped_column(String)  # stored as string decimal

    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    public_key_pem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # For digital signature verification

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    documents: Mapped[list["KYCDocument"]] = relationship("KYCDocument", back_populates="mandate")


class KYCDocument(Base):
    """
    Stores metadata for KYC documents (Passport, Utility Bill).
    """

    __tablename__ = "kyc_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("mandates.id"), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("entities.id"), nullable=True)

    doc_type: Mapped[str] = mapped_column(String, nullable=False)  # PASSPORT | UTILITY_BILL

    file_reference: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # S3 key or internal path

    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    mandate: Mapped[Optional["Mandate"]] = relationship("Mandate", back_populates="documents")
    doc_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
