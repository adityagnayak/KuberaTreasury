"""
NexusTreasury — API v1: Reports (VaR, GL, Variance)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.database import get_db
from app.services.fx_risk import calculate_var
from app.services.gl_engine import GLMappingEngine, TreasuryEvent
from app.services.rbac import RBACService

router = APIRouter(prefix="/reports", tags=["reports"])
rbac = RBACService()


class VaRRequest(BaseModel):
    pair: str
    position_value: str
    confidence: str = "0.95"


class VaRResponse(BaseModel):
    pair: str
    position_value: str
    var_amount: str
    confidence_level: str
    calculation_date: str
    worst_return: str


@router.post("/var", response_model=VaRResponse)
def compute_var(
    req: VaRRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "READ", "cash_positions")
    try:
        position_value = Decimal(req.position_value)
        confidence = Decimal(req.confidence)
    except Exception:
        raise HTTPException(status_code=422, detail="position_value and confidence must be decimals")

    result = calculate_var(req.pair, position_value, confidence)
    return VaRResponse(
        pair=result.pair,
        position_value=str(result.position_value),
        var_amount=str(result.var_amount),
        confidence_level=str(result.confidence_level),
        calculation_date=str(result.calculation_date),
        worst_return=str(result.worst_return),
    )


class GLEventRequest(BaseModel):
    event_id: str
    event_type: str
    amount: str
    currency: str
    metadata: dict = {}


class GLEntryResponse(BaseModel):
    entry_id: str
    event_type: str
    balanced: bool
    lines: list


@router.post("/gl/post", response_model=GLEntryResponse)
def post_gl_event(
    req: GLEventRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "WRITE", "initiate_payment")  # manager+
    try:
        amount = Decimal(req.amount)
    except Exception:
        raise HTTPException(status_code=422, detail="amount must be a decimal")

    engine = GLMappingEngine()
    event = TreasuryEvent(
        event_id=req.event_id,
        event_type=req.event_type,
        amount=amount,
        currency=req.currency,
        metadata=req.metadata,
    )
    entry = engine.post_journal(event)
    return GLEntryResponse(
        entry_id=entry.entry_id,
        event_type=entry.event_type,
        balanced=entry.balanced,
        lines=[
            {
                "account_code": l.account_code,
                "account_name": l.account_name,
                "debit": str(l.debit),
                "credit": str(l.credit),
                "currency": l.currency,
            }
            for l in entry.lines
        ],
    )
