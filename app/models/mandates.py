"""
NexusTreasury — ORM Models: E-BAM Mandates & KYC Documents (Phase 5)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, Date, DateTime, Enum, ForeignKey, String, Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Mandate(Base):
    """Bank account signing mandate with RSA public key (E-BAM)."""

    __tablename__ = "mandates"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False)
    signatory_name = Column(String(255), nullable=False)
    signatory_user_id = Column(String(255), nullable=False)
    public_key_pem = Column(Text, nullable=False)
    valid_from = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=False)
    status = Column(
        Enum("active", "expired", "revoked", name="mandate_status_enum"),
        nullable=False,
        default="active",
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    account = relationship("BankAccount", back_populates="mandates")


class KYCDocument(Base):
    """KYC document record with SHA-256 hash and expiry tracking."""

    __tablename__ = "kyc_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = Column(String(36), ForeignKey("entities.id"), nullable=False)
    doc_type = Column(String(100), nullable=False)
    doc_hash = Column(String(64), nullable=False)   # SHA-256 hex
    expiry_date = Column(Date, nullable=True)
    upload_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)

    entity = relationship("Entity", back_populates="kyc_documents")
