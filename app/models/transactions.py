"""
NexusTreasury — Transaction Models (Phase 1 & 2)
Includes core Transaction table, CashPositions, and Audit Logs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database import Base

# Trigger DDL for immutability (SQLite specific)
SQLITE_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS prevent_transaction_delete
BEFORE DELETE ON transactions
BEGIN
    SELECT RAISE(ABORT, 'Transactions are IMMUTABLE. Delete not allowed.');
END;

CREATE TRIGGER IF NOT EXISTS prevent_audit_update
BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'Audit logs are IMMUTABLE. Update not allowed.');
END;
"""


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("bank_accounts.id"), nullable=False)
    trn = Column(String, unique=True, index=True, nullable=False)  # Bank Reference
    entry_date = Column(Date, nullable=False)
    value_date = Column(Date, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False)

    # FIX: Added type annotation
    credit_debit_indicator: Column[str] = Column(
        Enum("CRDT", "DBIT", name="cdi_enum"), nullable=False
    )

    # FIX: Added type annotation
    status: Column[str] = Column(
        Enum("booked", "pending", "void", "forecast", name="txn_status_enum"),
        default="booked",
    )

    remittance_info = Column(Text)
    statement_id = Column(String, ForeignKey("statement_registry.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("BankAccount", back_populates="transactions")


class TransactionShadowArchive(Base):
    """
    Shadow table for deleted transactions (Soft Delete / Archive).
    In strict immutable mode, rows are never moved here, but this supports
    compliance "Right to be Forgotten" scenarios if configured.
    """

    __tablename__ = "transactions_shadow"

    id = Column(String, primary_key=True)
    original_transaction_id = Column(String, index=True)
    archived_at = Column(DateTime, default=datetime.utcnow)
    archived_by = Column(String)
    reason = Column(String)
    original_data_json = Column(Text)  # Full JSON dump of original row


class CashPosition(Base):
    """
    Daily aggregated cash position per account.
    Updated incrementally by ingestion service.
    """

    __tablename__ = "cash_positions"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("bank_accounts.id"), nullable=False)
    position_date = Column(Date, nullable=False, index=True)
    currency = Column(String(3), nullable=False)

    # Opening balance not strictly needed if we sum previous days,
    # but useful for performance snapshots.
    opening_balance = Column(Numeric(18, 2), default=0)

    # Net movements for the day
    entry_date_balance = Column(Numeric(18, 2), default=0)
    value_date_balance = Column(Numeric(18, 2), default=0)

    last_updated = Column(DateTime, default=datetime.utcnow)

    account = relationship("BankAccount", back_populates="cash_positions")

    __table_args__ = (
        Index("ix_cash_pos_acc_date", "account_id", "position_date", unique=True),
    )


class AuditLog(Base):
    """
    System-wide audit trail for critical actions (config changes, manual overrides).
    """

    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_id = Column(String, nullable=True)  # System or User ID

    # FIX: Added type annotation
    action: Column[str] = Column(String, nullable=False)

    table_name = Column(String, nullable=True)
    record_id = Column(String, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
