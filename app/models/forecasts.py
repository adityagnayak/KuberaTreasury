"""
NexusTreasury — ORM Models: Forecasts & Variance Alerts (Phase 2)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column, Date, DateTime, Enum, ForeignKey, Numeric, String, Text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class ForecastEntry(Base):
    """Liquidity forecast entries."""

    __tablename__ = "forecasts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id = Column(String(36), ForeignKey("bank_accounts.id"), nullable=False)
    currency = Column(String(3), nullable=False)
    expected_date = Column(Date, nullable=False)
    original_expected_date = Column(Date, nullable=True)   # pre-roll date
    forecast_amount = Column(Numeric(precision=28, scale=8), nullable=False)
    description = Column(Text, nullable=True)
    reconciliation_status = Column(
        Enum(
            "PENDING",
            "MATCHED",
            "UNMATCHED_FORECAST",
            "UNMATCHED_ACTUAL",
            "PARTIALLY_MATCHED",
            name="reconciliation_status_enum",
        ),
        nullable=False,
        default="PENDING",
    )
    matched_transaction_id = Column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    account = relationship("BankAccount")
    matched_transaction = relationship("Transaction")
    alerts = relationship("VarianceAlert", back_populates="forecast")


class VarianceAlert(Base):
    """High-priority variance alerts (immutable — no UPDATE via trigger)."""

    __tablename__ = "alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    alert_type = Column(String(50), nullable=False)   # HIGH_PRIORITY_INVESTIGATION
    account_id = Column(String(36), nullable=False)
    forecast_id = Column(String(36), ForeignKey("forecasts.id"), nullable=True)
    transaction_id = Column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    forecast_amount = Column(Numeric(precision=28, scale=8), nullable=True)
    actual_amount = Column(Numeric(precision=28, scale=8), nullable=True)
    variance_pct = Column(
        Numeric(precision=28, scale=8), nullable=True
    )   # NULL = infinite variance
    currency = Column(String(3), nullable=True)
    triggered_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    forecast = relationship("ForecastEntry", back_populates="alerts")
