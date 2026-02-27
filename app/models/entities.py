"""
NexusTreasury — Phase 1 & 2 Models: Entities, Accounts, Ingestion Registry
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import date, datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.transactions import Transaction, CashPosition
    from app.models.payments import Payment


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(
        Enum("parent", "subsidiary", "spv", name="entity_type_enum"),
        nullable=False,
        default="subsidiary",
    )
    country_code: Mapped[Optional[str]] = mapped_column(String(2))
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    accounts: Mapped[List["BankAccount"]] = relationship(
        "BankAccount", back_populates="entity"
    )


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    entity_id: Mapped[str] = mapped_column(
        String, ForeignKey("entities.id"), nullable=False
    )
    account_number: Mapped[Optional[str]] = mapped_column(String)
    iban: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    bic: Mapped[str] = mapped_column(String, nullable=False)
    account_name: Mapped[Optional[str]] = mapped_column(String)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bank_name: Mapped[Optional[str]] = mapped_column(String)
    country_code: Mapped[Optional[str]] = mapped_column(String(2))

    account_status: Mapped[str] = mapped_column(
        Enum("active", "closed", "blocked", name="account_status_enum"),
        default="active",
        nullable=False,
    )
    overdraft_limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)

    entity: Mapped["Entity"] = relationship("Entity", back_populates="accounts")
    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction", back_populates="account"
    )
    cash_positions: Mapped[List["CashPosition"]] = relationship(
        "CashPosition", back_populates="account"
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment", back_populates="debtor_account"
    )


class StatementRegistry(Base):
    """
    Tracks ingested statements (CAMT.053 / MT940) to prevent duplicates.
    Immutable log.
    """

    __tablename__ = "statement_registry"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("bank_accounts.id"), nullable=False
    )
    file_hash: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    message_id: Mapped[str] = mapped_column(String, nullable=False)
    legal_sequence_number: Mapped[Optional[str]] = mapped_column(String)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    import_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    imported_by: Mapped[Optional[str]] = mapped_column(String)
    format: Mapped[Optional[str]] = mapped_column(String)  # camt053 | mt940

    status: Mapped[str] = mapped_column(
        Enum("pending", "processed", "failed", name="ingest_status_enum"),
        default="pending",
    )


class StatementGap(Base):
    """Tracks missing statement dates."""

    __tablename__ = "statement_gaps"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("bank_accounts.id"), nullable=False
    )
    expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PeriodLock(Base):
    """
    Prevents modifications to transactions/balances before a certain date.
    Used for month-end closing.
    """

    __tablename__ = "period_locks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    locked_until: Mapped[date] = mapped_column(Date, nullable=False)
    locked_by: Mapped[Optional[str]] = mapped_column(String)
    locked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PendingPeriodAdjustment(Base):
    """
    When a statement arrives for a LOCKED period, we store the delta here
    instead of modifying the closed period's balance.
    """

    __tablename__ = "pending_period_adjustments"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, index=True, default=lambda: str(uuid.uuid4())
    )
    transaction_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("transactions.id")
    )
    account_id: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("bank_accounts.id")
    )
    value_date: Mapped[date] = mapped_column(Date, nullable=False)  # The locked date
    entry_date: Mapped[date] = mapped_column(
        Date, nullable=False
    )  # When we received it
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[Optional[str]] = mapped_column(
        String, default="pending"
    )  # pending | applied
