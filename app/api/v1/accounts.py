"""
NexusTreasury — API v1: Bank Accounts
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.database import get_db
from app.models.entities import BankAccount, Entity
from app.services.rbac import RBACService

router = APIRouter(prefix="/accounts", tags=["accounts"])
rbac = RBACService()


class AccountResponse(BaseModel):
    id: str
    entity_id: str
    iban: str
    bic: str
    account_name: Optional[str]
    currency: str
    overdraft_limit: str
    account_status: str

    class Config:
        from_attributes = True


class CreateAccountRequest(BaseModel):
    entity_id: str
    iban: str = Field(..., min_length=15, max_length=34)
    bic: str = Field(..., min_length=8, max_length=11)
    account_name: Optional[str] = None
    currency: str = Field(..., min_length=3, max_length=3)
    overdraft_limit: str = "0"


@router.get("/", response_model=List[AccountResponse])
def list_accounts(
    entity_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "READ", "transactions")
    query = db.query(BankAccount)
    if entity_id:
        query = query.filter_by(entity_id=entity_id)
    accounts = query.all()
    return [
        AccountResponse(
            id=a.id,
            entity_id=a.entity_id,
            iban=a.iban,
            bic=a.bic,
            account_name=a.account_name,
            currency=a.currency,
            overdraft_limit=str(a.overdraft_limit),
            account_status=a.account_status,
        )
        for a in accounts
    ]


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "READ", "transactions")
    account = db.query(BankAccount).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return AccountResponse(
        id=account.id,
        entity_id=account.entity_id,
        iban=account.iban,
        bic=account.bic,
        account_name=account.account_name,
        currency=account.currency,
        overdraft_limit=str(account.overdraft_limit),
        account_status=account.account_status,
    )


@router.post("/", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    req: CreateAccountRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "WRITE", "mandates")  # admin/manager only
    entity = db.query(Entity).filter_by(id=req.entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity {req.entity_id} not found")
    existing = db.query(BankAccount).filter_by(iban=req.iban).first()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Account with IBAN {req.iban} already exists"
        )

    account = BankAccount(
        entity_id=req.entity_id,
        iban=req.iban,
        bic=req.bic,
        account_name=req.account_name,
        currency=req.currency,
        overdraft_limit=req.overdraft_limit,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return AccountResponse(
        id=account.id,
        entity_id=account.entity_id,
        iban=account.iban,
        bic=account.bic,
        account_name=account.account_name,
        currency=account.currency,
        overdraft_limit=str(account.overdraft_limit),
        account_status=account.account_status,
    )
