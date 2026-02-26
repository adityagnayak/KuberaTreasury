"""
NexusTreasury — ORM Models: Debt & Investment Instruments (Phase 4)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, Date, DateTime, ForeignKey, Numeric, String, Text, Boolean,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Loan(Base):
    """Term loan / deposit / intercompany loan instrument."""

    __tablename__ = "loans"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    instrument_type = Column(String(20), nullable=False)   # LOAN | DEPOSIT | INTERCOMPANY
    instrument_subtype = Column(String(20), nullable=True)  # MM | BOND (for USD)
    currency = Column(String(3), nullable=False)
    principal = Column(Numeric(precision=28, scale=8), nullable=False)
    annual_rate = Column(Numeric(precision=18, scale=8), nullable=False)
    start_date = Column(Date, nullable=False)
    maturity_date = Column(Date, nullable=False)
    convention_override = Column(String(10), nullable=True)  # ACT/360 | ACT/365 | 30/360 | ACT/ACT
    counterparty_name = Column(String(255), nullable=True)
    entity_id = Column(String(36), ForeignKey("entities.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    entity = relationship("Entity")


class FXForward(Base):
    """FX forward contract."""

    __tablename__ = "fx_forwards"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    currency_pair = Column(String(7), nullable=False)    # e.g. EUR/USD
    notional = Column(Numeric(precision=28, scale=8), nullable=False)
    forward_rate = Column(Numeric(precision=18, scale=8), nullable=False)
    maturity_date = Column(Date, nullable=False)
    adjusted_maturity_date = Column(Date, nullable=True)
    hedge_designation = Column(String(50), nullable=True)  # CASH_FLOW | FAIR_VALUE | NET_INVESTMENT
    fair_value = Column(Numeric(precision=28, scale=8), nullable=True)
    entity_id = Column(String(36), ForeignKey("entities.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    entity = relationship("Entity")


class MoneyMarketFund(Base):
    """Money market fund investment."""

    __tablename__ = "mm_funds"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fund_name = Column(String(255), nullable=False)
    currency = Column(String(3), nullable=False)
    invested_amount = Column(Numeric(precision=28, scale=8), nullable=False)
    nav_per_unit = Column(Numeric(precision=18, scale=8), nullable=True)
    units_held = Column(Numeric(precision=28, scale=8), nullable=True)
    investment_date = Column(Date, nullable=False)
    redemption_date = Column(Date, nullable=True)
    entity_id = Column(String(36), ForeignKey("entities.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    entity = relationship("Entity")


class GLJournalEntry(Base):
    """Persisted double-entry general ledger journal entry header."""

    __tablename__ = "gl_journal_entries"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type = Column(String(50), nullable=False)
    event_id = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    posted_by = Column(String(255), nullable=True)
    posting_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    is_balanced = Column(Boolean, nullable=False, default=True)

    lines = relationship("GLJournalLine", back_populates="entry")


class GLJournalLine(Base):
    """Single debit or credit line within a GL journal entry."""

    __tablename__ = "gl_journal_lines"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entry_id = Column(String(36), ForeignKey("gl_journal_entries.id"), nullable=False)
    account_code = Column(String(10), nullable=False)
    account_name = Column(String(100), nullable=False)
    debit = Column(Numeric(precision=28, scale=8), nullable=False, default=0)
    credit = Column(Numeric(precision=28, scale=8), nullable=False, default=0)
    currency = Column(String(3), nullable=False)
    description = Column(String(500), nullable=True)

    entry = relationship("GLJournalEntry", back_populates="lines")


class PositionLock(Base):
    """Application-level advisory lock table for concurrent position updates (Phase 5)."""

    __tablename__ = "position_locks"

    account_id = Column(String(36), primary_key=True)
    locked_by = Column(String(255), nullable=False)
    locked_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
