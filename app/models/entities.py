"""
NexusTreasury — ORM Models: Entities & Bank Accounts (Phase 1)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Enum,
    ForeignKey, Numeric, String, UniqueConstraint, Date,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Entity(Base):
    """Legal entities (Parent/Subsidiary)."""

    __tablename__ = "entities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    entity_type = Column(
        Enum("parent", "subsidiary", name="entity_type_enum"),
        nullable=False,
    )
    base_currency = Column(String(3), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("length(base_currency) = 3", name="ck_entities_currency_len"),
    )

    bank_accounts = relationship("BankAccount", back_populates="entity")
    kyc_documents = relationship("KYCDocument", back_populates="entity")


class BankAccount(Base):
    """Bank accounts with IBAN validation, BIC, overdraft limit."""

    __tablename__ = "bank_accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = Column(String(36), ForeignKey("entities.id"), nullable=False)
    iban = Column(String(34), nullable=False, unique=True)
    bic = Column(String(11), nullable=False)
    account_name = Column(String(255), nullable=True)
    currency = Column(String(3), nullable=False)
    overdraft_limit = Column(
        Numeric(precision=28, scale=8), nullable=False, default=Decimal("0")
    )
    account_status = Column(
        Enum("active", "frozen", "expired_mandate", name="account_status_enum"),
        nullable=False,
        default="active",
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint(
            "length(bic) BETWEEN 8 AND 11", name="ck_bank_accounts_bic_len"
        ),
        CheckConstraint(
            "overdraft_limit >= 0", name="ck_bank_accounts_overdraft_positive"
        ),
        CheckConstraint(
            "length(currency) = 3", name="ck_bank_accounts_currency_len"
        ),
    )

    entity = relationship("Entity", back_populates="bank_accounts")
    transactions = relationship("Transaction", back_populates="account")
    cash_positions = relationship("CashPosition", back_populates="account")
    statement_gaps = relationship("StatementGap", back_populates="account")
    payments = relationship("Payment", back_populates="debtor_account")
    mandates = relationship("Mandate", back_populates="account")


class StatementRegistry(Base):
    """Tracks every imported bank statement file."""

    __tablename__ = "statement_registry"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False)
    file_hash = Column(String(64), nullable=False)
    message_id = Column(String(255), nullable=False)
    legal_sequence_number = Column(String(50), nullable=True)
    statement_date = Column(Date, nullable=True)
    import_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(
        Enum(
            "pending", "processed", "failed", "duplicate",
            name="stmt_status_enum",
        ),
        nullable=False,
        default="pending",
    )
    imported_by = Column(String(255), nullable=True)
    format = Column(String(20), nullable=True)  # 'camt053' | 'mt940'

    __table_args__ = (
        UniqueConstraint(
            "message_id", "legal_sequence_number",
            name="uq_statement_message_seq",
        ),
    )


class StatementGap(Base):
    """Records detected missing bank statement dates per account."""

    __tablename__ = "statement_gaps"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False)
    expected_date = Column(Date, nullable=False)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    resolved = Column(Boolean, nullable=False, default=False)
    resolved_at = Column(DateTime, nullable=True)

    account = relationship("BankAccount", back_populates="statement_gaps")


class PeriodLock(Base):
    """Accounting period locks."""

    __tablename__ = "period_locks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    locked_until = Column(Date, nullable=False)
    locked_by = Column(String(255), nullable=True)
    locked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    note = Column(String(500), nullable=True)


class PendingPeriodAdjustment(Base):
    """Transactions blocked by period lock, awaiting manual review."""

    __tablename__ = "pending_period_adjustments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    transaction_id = Column(String(36), nullable=False)
    account_id = Column(String(36), nullable=False)
    value_date = Column(Date, nullable=False)
    entry_date = Column(Date, nullable=False)
    amount = Column(Numeric(precision=28, scale=8), nullable=False)
    currency = Column(String(3), nullable=False)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reviewed = Column(Boolean, nullable=False, default=False)
