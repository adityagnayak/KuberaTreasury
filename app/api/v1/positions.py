"""
NexusTreasury — API v1: Cash Positions
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.database import get_db
from app.services.cash_positioning import CashPositioningService, FXRateCache
from app.services.rbac import RBACService

router = APIRouter(prefix="/positions", tags=["positions"])
rbac = RBACService()

_fx_cache = FXRateCache()


class PositionResponse(BaseModel):
    account_id: str
    currency: str
    as_of_date: str
    balance: str
    balance_type: str


@router.get("/{account_id}", response_model=PositionResponse)
def get_position(
    account_id: str,
    as_of_date: Optional[date] = None,
    use_value_date: bool = True,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "READ", "cash_positions")
    service = CashPositioningService(db, _fx_cache)
    pos = service.get_position(account_id, as_of_date or date.today(), use_value_date)
    return PositionResponse(
        account_id=pos.account_id,
        currency=pos.currency,
        as_of_date=str(pos.as_of_date),
        balance=str(pos.balance),
        balance_type=pos.balance_type,
    )
