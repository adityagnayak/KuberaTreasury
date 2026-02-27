"""
NexusTreasury — E-BAM Models (Phase 5)
Bank Mandates and Signatory Management.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Mandate(Base):
    """
    Represents authority to sign payments on a specific account.
    """

    __tablename__ = "mandates"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("bank_accounts.id"), nullable=False)

    signatory_name = Column(String, nullable=False)
    signatory_user_id = Column(String, nullable=True)  # Link to IAM user

    # FIX: Added type annotation
    status: Column[str] = Column(
        Enum("active", "revoked", "expired", name="mandate_status_enum"),
        default="active",
        nullable=False,
    )

    role = Column(String)  # e.g., "A-Signatory", "B-Signatory"
    limit_currency = Column(String(3))
    single_payment_limit = Column(
        String
    )  # stored as string decimal to avoid precision loss

    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=True)

    public_key_pem = Column(Text, nullable=True)  # For digital signature verification

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    documents = relationship("KYCDocument", back_populates="mandate")


class KYCDocument(Base):
    """
    Stores metadata for KYC documents (Passport, Utility Bill).
    """

    __tablename__ = "kyc_documents"

    id = Column(String, primary_key=True, index=True)
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=True)

    doc_type = Column(String, nullable=False)  # PASSPORT | UTILITY_BILL
    file_reference = Column(String, nullable=False)  # S3 key or internal path
    expiry_date = Column(Date, nullable=True)

    uploaded_at = Column(DateTime, default=datetime.utcnow)

    mandate = relationship("Mandate", back_populates="documents")
