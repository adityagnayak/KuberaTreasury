"""Intercompany — FastAPI v1 router."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import AuthUser, DBSession
from app.services.intercompany_service import (
    AgeingReport,
    CirSummary,
    IntercompanyService,
    IntercompanyTransactionCreate,
    IntercompanyTransactionRead,
)

router = APIRouter(prefix="/intercompany", tags=["Intercompany & CIR"])


def _svc(db: DBSession, user: AuthUser) -> IntercompanyService:
    return IntercompanyService(db, user.tenant_id, user.user_id)


@router.post(
    "/transactions",
    response_model=IntercompanyTransactionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record intercompany transaction with TP rate validation (±150bps)",
)
async def create_transaction(
    payload: IntercompanyTransactionCreate,
    svc: Annotated[IntercompanyService, Depends(_svc)],
) -> IntercompanyTransactionRead:
    tx = await svc.create_transaction(payload)
    return IntercompanyTransactionRead.model_validate(tx)


@router.get(
    "/transactions",
    response_model=list[IntercompanyTransactionRead],
    summary="List intercompany transactions",
)
async def list_transactions(
    svc: Annotated[IntercompanyService, Depends(_svc)],
    transaction_type: str | None = Query(default=None),
    matched: bool | None = Query(default=None),
) -> list[IntercompanyTransactionRead]:
    txs = await svc.list_transactions(
        transaction_type=transaction_type, matched=matched
    )
    return [IntercompanyTransactionRead.model_validate(t) for t in txs]


@router.get(
    "/transactions/{transaction_id}",
    response_model=IntercompanyTransactionRead,
    summary="Get intercompany transaction",
)
async def get_transaction(
    transaction_id: uuid.UUID,
    svc: Annotated[IntercompanyService, Depends(_svc)],
) -> IntercompanyTransactionRead:
    tx = await svc.get_transaction(transaction_id)
    return IntercompanyTransactionRead.model_validate(tx)


@router.post(
    "/transactions/{transaction_id}/match",
    response_model=IntercompanyTransactionRead,
    summary="Mark intercompany transaction as matched (payable/receivable agreed)",
)
async def match_transaction(
    transaction_id: uuid.UUID,
    svc: Annotated[IntercompanyService, Depends(_svc)],
) -> IntercompanyTransactionRead:
    tx = await svc.match_transaction(transaction_id)
    return IntercompanyTransactionRead.model_validate(tx)


@router.get(
    "/ageing",
    response_model=AgeingReport,
    summary="Ageing report: unmatched transactions bucketed 0-30 / 31-60 / 61-90 / 90+ days",
)
async def ageing_report(
    svc: Annotated[IntercompanyService, Depends(_svc)],
    reference_date: date = Query(default_factory=date.today),
) -> AgeingReport:
    return await svc.ageing_report(reference_date)


@router.post(
    "/cir",
    response_model=CirSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Calculate and record Corporate Interest Restriction (TIOPA 2010 Part 10)",
)
async def calculate_cir(
    period_start: date,
    period_end: date,
    gross_interest_expense: Decimal,
    gross_interest_income: Decimal,
    restricted_amount: Decimal | None = None,
    svc: Annotated[IntercompanyService, Depends(_svc)] = ...,  # type: ignore[assignment]
) -> CirSummary:
    return await svc.calculate_cir(
        period_start=period_start,
        period_end=period_end,
        gross_interest_expense=gross_interest_expense,
        gross_interest_income=gross_interest_income,
        restricted_amount=restricted_amount,
    )
