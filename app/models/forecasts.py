"""
NexusTreasury — Phase 2 Models: Cash Flow Forecasting
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ForecastEntry(Base):
    """
    Represents a projected cash flow (Manual or System generated).
    """

    __tablename__ = "forecast_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))

    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("bank_accounts.id"), nullable=False, index=True
    )

    # Primary amount column used by LiquidityForecastingService.ingest_forecast().
    forecast_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2), nullable=True)

    entity_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("entities.id"), nullable=True)

    expected_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    direction: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default="INFLOW")  # INFLOW | OUTFLOW

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(String)

    source_system: Mapped[Optional[str]] = mapped_column(String, default="MANUAL")
    probability: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), default=100)

    reconciliation_status: Mapped[str] = mapped_column(
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
        default="PENDING",
    )

    matched_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    original_expected_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VarianceAlert(Base):
    """
    Stores high-priority alerts when actuals deviate significantly from forecasts.
    """

    __tablename__ = "variance_alerts"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    alert_type: Mapped[str] = mapped_column(String, nullable=False)

    account_id: Mapped[Optional[str]] = mapped_column(String, index=True)
    forecast_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("forecast_entries.id"), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    forecast_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    actual_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    variance_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    currency: Mapped[Optional[str]] = mapped_column(String(3))

    notes: Mapped[Optional[str]] = mapped_column(String)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
