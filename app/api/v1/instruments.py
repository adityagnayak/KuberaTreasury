"""
NexusTreasury — API v1: Debt & Investment Instruments
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.database import get_db
from app.services.debt_ledger import DebtInstrument, DebtInvestmentLedger
from app.services.rbac import RBACService

router = APIRouter(prefix="/instruments", tags=["instruments"])
rbac = RBACService()


class InterestCalculationRequest(BaseModel):
    instrument_type: str = "LOAN"
    currency: str
    principal: str
    annual_rate: str
    start_date: date
    maturity_date: date
    convention_override: Optional[str] = None
    instrument_subtype: Optional[str] = None


class InterestCalculationResponse(BaseModel):
    interest_amount: str
    accrual_period_days: int
    convention_used: str
    is_negative_rate: bool


@router.post("/calculate-interest", response_model=InterestCalculationResponse)
def calculate_interest(
    req: InterestCalculationRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "READ", "cash_positions")
    try:
        principal = Decimal(req.principal)
        rate = Decimal(req.annual_rate)
    except Exception:
        raise HTTPException(
            status_code=422, detail="principal and annual_rate must be decimals"
        )

    ledger = DebtInvestmentLedger()
    instrument = DebtInstrument(
        instrument_id="temp",
        instrument_type=req.instrument_type,
        currency=req.currency,
        principal=principal,
        rate=rate,
        start_date=req.start_date,
        maturity_date=req.maturity_date,
        convention_override=req.convention_override,
        instrument_subtype=req.instrument_subtype,
    )
    result = ledger.calculate_interest(instrument)
    return InterestCalculationResponse(
        interest_amount=str(result.interest_amount),
        accrual_period_days=result.accrual_period_days,
        convention_used=result.convention_used,
        is_negative_rate=result.is_negative_rate,
    )
