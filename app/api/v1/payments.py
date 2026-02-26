"""
NexusTreasury — API v1: Payments
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import CurrentUser, get_current_user
from app.database import get_db
from app.models.payments import Payment
from app.services.payment_factory import PaymentRequest, PaymentService
from app.services.rbac import RBACService

router = APIRouter(prefix="/payments", tags=["payments"])
rbac = RBACService()


class InitiatePaymentRequest(BaseModel):
    debtor_account_id: str
    debtor_iban: str
    beneficiary_name: str
    beneficiary_bic: str
    beneficiary_iban: str
    beneficiary_country: str = Field(..., min_length=2, max_length=2)
    amount: str
    currency: str = Field(..., min_length=3, max_length=3)
    execution_date: str
    remittance_info: Optional[str] = None


class PaymentResponse(BaseModel):
    id: str
    status: str
    maker_user_id: str
    amount: str
    currency: str
    end_to_end_id: str
    beneficiary_name: str


@router.post("/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def initiate_payment(
    req: InitiatePaymentRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "WRITE", "initiate_payment")
    try:
        amount = Decimal(req.amount)
    except Exception:
        raise HTTPException(status_code=422, detail="amount must be a valid decimal")

    service = PaymentService(db)
    payment_req = PaymentRequest(
        debtor_account_id=req.debtor_account_id,
        debtor_iban=req.debtor_iban,
        beneficiary_name=req.beneficiary_name,
        beneficiary_bic=req.beneficiary_bic,
        beneficiary_iban=req.beneficiary_iban,
        beneficiary_country=req.beneficiary_country,
        amount=amount,
        currency=req.currency,
        execution_date=req.execution_date,
        remittance_info=req.remittance_info,
    )
    payment = service.initiate_payment(payment_req, current_user.user_id)
    return PaymentResponse(
        id=payment.id,
        status=payment.status,
        maker_user_id=payment.maker_user_id,
        amount=str(payment.amount),
        currency=payment.currency,
        end_to_end_id=payment.end_to_end_id,
        beneficiary_name=payment.beneficiary_name,
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    rbac.check(current_user.role, "READ", "payments")
    payment = db.query(Payment).filter_by(id=payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found")
    return PaymentResponse(
        id=payment.id,
        status=payment.status,
        maker_user_id=payment.maker_user_id,
        amount=str(payment.amount),
        currency=payment.currency,
        end_to_end_id=payment.end_to_end_id,
        beneficiary_name=payment.beneficiary_name,
    )
