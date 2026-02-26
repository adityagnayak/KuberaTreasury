"""
NexusTreasury — API v1: Forecasts & Variance Reports
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.database import get_db
from app.services.forecasting import ForecastEntryInput, LiquidityForecastingService
from app.services.rbac import RBACService

router = APIRouter(prefix="/forecasts", tags=["forecasts"])
rbac = RBACService()


class CreateForecastRequest(BaseModel):
    account_id: str
    currency: str
    expected_date: date
    forecast_amount: str
    description: Optional[str] = None
    auto_roll_bday: bool = True


class VarianceReportResponse(BaseModel):
    from_date: str
    to_date: str
    entity_id: Optional[str]
    total_forecast: str
    total_actual: str
    net_variance: str
    variance_pct: Optional[str]
    high_priority_count: int
    detail_rows: List[dict]


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_forecast(
    req: CreateForecastRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "WRITE", "forecasts")
    try:
        amount = Decimal(req.forecast_amount)
    except Exception:
        raise HTTPException(
            status_code=422, detail="forecast_amount must be a valid decimal"
        )

    service = LiquidityForecastingService(db)
    service.ingest_forecast(
        [
            ForecastEntryInput(
                account_id=req.account_id,
                currency=req.currency,
                expected_date=req.expected_date,
                forecast_amount=amount,
                description=req.description,
                auto_roll_bday=req.auto_roll_bday,
            )
        ]
    )
    return {"status": "created"}


@router.get("/variance-report", response_model=VarianceReportResponse)
def get_variance_report(
    from_date: date,
    to_date: date,
    entity_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "READ", "forecasts")
    service = LiquidityForecastingService(db)
    report = service.get_variance_report(from_date, to_date, entity_id)
    return VarianceReportResponse(
        from_date=str(report.from_date),
        to_date=str(report.to_date),
        entity_id=report.entity_id,
        total_forecast=str(report.total_forecast),
        total_actual=str(report.total_actual),
        net_variance=str(report.net_variance),
        variance_pct=str(report.variance_pct) if report.variance_pct else None,
        high_priority_count=len(report.high_priority_items),
        detail_rows=[
            {
                k: str(v) if not isinstance(v, (str, bool, type(None))) else v
                for k, v in row.items()
            }
            for row in report.detail_rows
        ],
    )
