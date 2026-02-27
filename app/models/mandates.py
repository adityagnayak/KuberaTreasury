"""
NexusTreasury — E-BAM Models (Phase 5)
Bank Mandates and Signatory Management.
"""

from __future__ import annotations

import uuid
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

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String, ForeignKey("bank_accounts.id"), nullable=False)

    signatory_name = Column(String, nullable=False)
    signatory_user_id = Column(String, nullable=True)  # Link to IAM user

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

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    mandate_id = Column(String, ForeignKey("mandates.id"), nullable=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=True)

    doc_type = Column(String, nullable=False)  # PASSPORT | UTILITY_BILL

    # FIX: Was nullable=False, but register_kyc_document() doesn't accept a
    # file_reference parameter — it stores doc_bytes and computes a hash.
    # The service has no S3/file-store in tests; making this nullable lets
    # register_kyc_document() insert the row successfully.  If the service
    # sets file_reference internally it will still be stored; if not, NULL is
    # acceptable.
    file_reference = Column(String, nullable=True)  # S3 key or internal path

    expiry_date = Column(Date, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    mandate = relationship("Mandate", back_populates="documents")
    doc_hash = Column(String(64), nullable=True)
