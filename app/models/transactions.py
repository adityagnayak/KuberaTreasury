"""
NexusTreasury — Transaction Models (Phase 1 & 2)
Includes core Transaction table, CashPositions, and Audit Logs.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.entities import BankAccount

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

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(String, ForeignKey("bank_accounts.id"), nullable=False)
    trn: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)  # Bank Reference
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    credit_debit_indicator: Mapped[str] = mapped_column(
        Enum("CRDT", "DBIT", name="cdi_enum"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        Enum("booked", "pending", "void", "forecast", name="txn_status_enum"),
        default="booked",
    )

    remittance_info: Mapped[Optional[str]] = mapped_column(Text)
    statement_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("statement_registry.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["BankAccount"] = relationship("BankAccount", back_populates="transactions")


class TransactionShadowArchive(Base):
    """
    Shadow table for deleted transactions (Soft Delete / Archive).
    """

    __tablename__ = "transactions_shadow"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    original_transaction_id: Mapped[Optional[str]] = mapped_column(String, index=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    archived_by: Mapped[Optional[str]] = mapped_column(String)
    reason: Mapped[Optional[str]] = mapped_column(String)
    original_data_json: Mapped[Optional[str]] = mapped_column(Text)  # Full JSON dump of original row


class CashPosition(Base):
    """
    Daily aggregated cash position per account.
    Updated incrementally by ingestion service.
    """

    __tablename__ = "cash_positions"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(String, ForeignKey("bank_accounts.id"), nullable=False)
    position_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    entry_date_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    value_date_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["BankAccount"] = relationship("BankAccount", back_populates="cash_positions")

    __table_args__ = (
        Index("ix_cash_pos_acc_date", "account_id", "position_date", unique=True),
    )


class AuditLog(Base):
    """
    System-wide audit trail for critical actions.
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    action: Mapped[str] = mapped_column(String, nullable=False)

    table_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
