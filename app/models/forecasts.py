"""
NexusTreasury — Phase 2 Models: Cash Flow Forecasting
"""

from __future__ import annotations

import uuid
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

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))

    account_id = Column(
        String, ForeignKey("bank_accounts.id"), nullable=False, index=True
    )

    # Primary amount column used by LiquidityForecastingService.ingest_forecast().
    # The service sets `forecast_amount` — this is the canonical field.
    forecast_amount = Column(Numeric(18, 2), nullable=False)

    # FIX: `amount` was a second nullable=False column that the service never
    # populates, causing "NOT NULL constraint failed: forecast_entries.amount"
    # on every ingest_forecast() call.  Made nullable — callers that need a
    # legacy `amount` alias can still set it, but leaving it NULL is fine.
    amount = Column(Numeric(18, 2), nullable=True)

    entity_id = Column(String, ForeignKey("entities.id"), nullable=True)

    expected_date = Column(Date, nullable=False, index=True)

    # FIX: `direction` was nullable=False with no default, but ingest_forecast()
    # never sets it.  Gave it a sensible default so inserts succeed without
    # callers being required to specify directionality.
    direction = Column(String(10), nullable=True, default="INFLOW")  # INFLOW | OUTFLOW

    currency = Column(String(3), nullable=False)
    category = Column(String)
    description = Column(String)

    source_system = Column(String, default="MANUAL")
    probability = Column(Numeric(5, 2), default=100)

    reconciliation_status: Column[str] = Column(
        Enum(
            "projected",
            "reconciled",
            "variance",
            "PENDING",
            "MATCHED",
            "UNMATCHED_FORECAST",
            "PARTIALLY_MATCHED",
            name="forecast_status_enum",
        ),
        default="PENDING",  # FIX: was "projected" — service filters on "PENDING"
        # in reconcile_actuals(); rows defaulting to "projected"
        # would never be picked up for reconciliation.
    )

    matched_transaction_id = Column(String, nullable=True)
    original_expected_date = Column(Date, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class VarianceAlert(Base):
    """
    Stores high-priority alerts when actuals deviate significantly from forecasts.
    """

    __tablename__ = "variance_alerts"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    alert_type = Column(String, nullable=False)

    account_id = Column(String, index=True)
    forecast_id = Column(String, ForeignKey("forecast_entries.id"), nullable=True)
    transaction_id = Column(String, nullable=True)

    forecast_amount = Column(Numeric(18, 2))
    actual_amount = Column(Numeric(18, 2))
    variance_pct = Column(Numeric(10, 2))
    currency = Column(String(3))

    notes = Column(String)
    triggered_at = Column(DateTime, default=datetime.utcnow)
