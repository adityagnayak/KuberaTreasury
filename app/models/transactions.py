"""
NexusTreasury — ORM Models: Transactions, Cash Positions, Audit Logs (Phase 1)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Transaction(Base):
    """Financial transactions linked to bank accounts."""

    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    trn = Column(String(255), nullable=False, unique=True)
    account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False)
    entry_date = Column(Date, nullable=False)
    value_date = Column(Date, nullable=False)
    amount = Column(Numeric(precision=28, scale=8), nullable=False)
    currency = Column(String(3), nullable=False)
    remittance_info = Column(Text, nullable=True)
    credit_debit_indicator = Column(
        Enum("CRDT", "DBIT", name="crdt_dbit_enum"),
        nullable=False,
    )
    status = Column(
        Enum(
            "booked",
            "pending",
            "rejected",
            "pending_period_adj",
            name="txn_status_enum",
        ),
        nullable=False,
        default="booked",
    )
    statement_id = Column(
        String(36), ForeignKey("statement_registry.id"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("length(currency) = 3", name="ck_transactions_currency_len"),
    )

    account = relationship("BankAccount", back_populates="transactions")


class TransactionShadowArchive(Base):
    """Soft-delete archive for transactions (immutable)."""

    __tablename__ = "transactions_shadow_archive"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    original_id = Column(String(36), nullable=False)
    trn = Column(String(255), nullable=False)
    account_id = Column(String(36), nullable=False)
    entry_date = Column(Date, nullable=False)
    value_date = Column(Date, nullable=False)
    amount = Column(Numeric(precision=28, scale=8), nullable=False)
    currency = Column(String(3), nullable=False)
    remittance_info = Column(Text, nullable=True)
    credit_debit_indicator = Column(String(4), nullable=False)
    status = Column(String(30), nullable=False)
    statement_id = Column(String(36), nullable=True)
    original_created_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    archived_reason = Column(String(255), nullable=True, default="DELETE_ATTEMPTED")


class CashPosition(Base):
    """Snapshot of cash positions per account, date, and currency."""

    __tablename__ = "cash_positions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False)
    position_date = Column(Date, nullable=False)
    currency = Column(String(3), nullable=False)
    entry_date_balance = Column(
        Numeric(precision=28, scale=8), nullable=False, default=0
    )
    value_date_balance = Column(
        Numeric(precision=28, scale=8), nullable=False, default=0
    )
    last_updated = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "position_date", "currency", name="uq_cash_position"
        ),
        CheckConstraint("length(currency) = 3", name="ck_cash_positions_currency_len"),
    )

    account = relationship("BankAccount", back_populates="cash_positions")


class AuditLog(Base):
    """Immutable audit trail — no UPDATE or DELETE permitted via DB triggers."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    table_name = Column(String(100), nullable=False)
    record_id = Column(String(36), nullable=True)
    action = Column(
        Enum(
            "INSERT",
            "UPDATE",
            "DELETE",
            "DUPLICATE_ATTEMPT",
            "GAP_DETECTED",
            name="audit_action_enum",
        ),
        nullable=False,
    )
    old_value = Column(Text, nullable=True)  # JSON
    new_value = Column(Text, nullable=True)  # JSON
    user_id = Column(String(255), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)


# ─── SQLite Triggers ──────────────────────────────────────────────────────────
# Installed at startup via app.database.init_db()

SQLITE_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS trg_audit_logs_block_update
BEFORE UPDATE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'IMMUTABLE: Updates to audit_logs are not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_logs_block_delete
BEFORE DELETE ON audit_logs
BEGIN
    SELECT RAISE(ABORT, 'IMMUTABLE: Deletes from audit_logs are not permitted');
END;

CREATE TRIGGER IF NOT EXISTS trg_transactions_audit_insert
AFTER INSERT ON transactions
BEGIN
    INSERT INTO audit_logs (id, table_name, record_id, action, old_value, new_value, user_id, timestamp)
    VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1,1) ||
        substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))),
        'transactions',
        NEW.id,
        'INSERT',
        NULL,
        json_object(
            'id', NEW.id,
            'trn', NEW.trn,
            'account_id', NEW.account_id,
            'entry_date', NEW.entry_date,
            'value_date', NEW.value_date,
            'amount', CAST(NEW.amount AS TEXT),
            'currency', NEW.currency,
            'status', NEW.status
        ),
        NULL,
        datetime('now')
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_transactions_audit_update
AFTER UPDATE ON transactions
BEGIN
    INSERT INTO audit_logs (id, table_name, record_id, action, old_value, new_value, user_id, timestamp)
    VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1,1) ||
        substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))),
        'transactions',
        OLD.id,
        'UPDATE',
        json_object(
            'id', OLD.id,
            'trn', OLD.trn,
            'amount', CAST(OLD.amount AS TEXT),
            'status', OLD.status
        ),
        json_object(
            'id', NEW.id,
            'trn', NEW.trn,
            'amount', CAST(NEW.amount AS TEXT),
            'status', NEW.status
        ),
        NULL,
        datetime('now')
    );
END;

CREATE TRIGGER IF NOT EXISTS trg_transactions_shadow_on_delete
BEFORE DELETE ON transactions
BEGIN
    INSERT INTO transactions_shadow_archive (
        id, original_id, trn, account_id, entry_date, value_date,
        amount, currency, remittance_info, credit_debit_indicator,
        status, statement_id, original_created_at, archived_at, archived_reason
    )
    VALUES (
        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
        substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1,1) ||
        substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6))),
        OLD.id, OLD.trn, OLD.account_id, OLD.entry_date, OLD.value_date,
        OLD.amount, OLD.currency, OLD.remittance_info, OLD.credit_debit_indicator,
        OLD.status, OLD.statement_id, OLD.created_at, datetime('now'),
        'DELETE_ATTEMPTED'
    );
    SELECT RAISE(ABORT, 'IMMUTABLE: Deletes from transactions are not permitted; row archived to transactions_shadow_archive');
END;
"""
