"""
NexusTreasury — Phase 2 Models: Cash Flow Forecasting
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
)

from app.database import Base


class ForecastEntry(Base):
    """
    Represents a projected cash flow (Manual or System generated).
    """

    __tablename__ = "forecast_entries"

    id = Column(String, primary_key=True, index=True)
    entity_id = Column(String, ForeignKey("entities.id"), nullable=False)

    flow_date = Column(Date, nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    direction = Column(String(10), nullable=False)  # INFLOW | OUTFLOW

    category = Column(String)  # AP, AR, Payroll, Tax, Treasury
    description = Column(String)

    source_system = Column(String, default="MANUAL")
    probability = Column(Numeric(5, 2), default=100)  # 0-100%

    # FIX: Added type annotation
    reconciliation_status: Column[str] = Column(
        Enum("projected", "reconciled", "variance", name="forecast_status_enum"),
        default="projected",
    )

    actual_transaction_id = Column(String, nullable=True)  # Link to realized txn

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
