"""
NexusTreasury — Phase 1 & 2 Models: Entities, Accounts, Ingestion Registry
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Entity(Base):
    __tablename__ = "entities"

    id = Column(String, primary_key=True, index=True)  # UUID
    name = Column(String, nullable=False)
    # FIX: Added type annotation
    entity_type: Column[str] = Column(
        Enum("parent", "subsidiary", "spv", name="entity_type_enum"),
        nullable=False,
        default="subsidiary",
    )
    country_code = Column(String(2))
    base_currency = Column(String(3), nullable=False, default="EUR")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    accounts = relationship("BankAccount", back_populates="entity")


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(String, primary_key=True, index=True)  # UUID
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)
    account_number = Column(String)
    iban = Column(String, unique=True, index=True, nullable=False)
    bic = Column(String, nullable=False)
    account_name = Column(String)
    currency = Column(String(3), nullable=False)
    bank_name = Column(String)
    country_code = Column(String(2))

    # FIX: Added type annotation
    account_status: Column[str] = Column(
        Enum("active", "closed", "blocked", name="account_status_enum"),
        default="active",
        nullable=False,
    )
    overdraft_limit = Column(Numeric(18, 2), default=0)

    entity = relationship("Entity", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")
    cash_positions = relationship("CashPosition", back_populates="account")


class StatementRegistry(Base):
    """
    Tracks ingested statements (CAMT.053 / MT940) to prevent duplicates.
    Immutable log.
    """

    __tablename__ = "statement_registry"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("bank_accounts.id"), nullable=False)
    file_hash = Column(String, unique=True, index=True, nullable=False)
    message_id = Column(String, nullable=False)
    legal_sequence_number = Column(String)
    statement_date = Column(Date, nullable=False)
    import_timestamp = Column(DateTime, default=datetime.utcnow)
    imported_by = Column(String)
    format = Column(String)  # camt053 | mt940

    # FIX: Added type annotation
    status: Column[str] = Column(
        Enum("pending", "processed", "failed", name="ingest_status_enum"),
        default="pending",
    )


class StatementGap(Base):
    """Tracks missing statement dates."""

    __tablename__ = "statement_gaps"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("bank_accounts.id"), nullable=False)
    expected_date = Column(Date, nullable=False)
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


class PeriodLock(Base):
    """
    Prevents modifications to transactions/balances before a certain date.
    Used for month-end closing.
    """

    __tablename__ = "period_locks"

    id = Column(String, primary_key=True, index=True)
    locked_until = Column(Date, nullable=False)
    locked_by = Column(String)
    locked_at = Column(DateTime, default=datetime.utcnow)


class PendingPeriodAdjustment(Base):
    """
    When a statement arrives for a LOCKED period, we store the delta here
    instead of modifying the closed period's balance.
    """

    __tablename__ = "pending_period_adjustments"

    id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.id"))
    account_id = Column(String, ForeignKey("bank_accounts.id"))
    value_date = Column(Date, nullable=False)  # The locked date
    entry_date = Column(Date, nullable=False)  # When we received it
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    reason = Column(String)
    status = Column(String, default="pending")  # pending | applied
