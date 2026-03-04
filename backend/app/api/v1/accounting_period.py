"""Accounting Period — FastAPI v1 router."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import AuthUser, DBSession
from app.services.accounting_period_service import (
    AccountingPeriodCreate,
    AccountingPeriodRead,
    AccountingPeriodService,
    CtTaxDates,
    HardCloseRequest,
    ReopenRequest,
    SoftCloseRequest,
    YearEndRolloverRequest,
)

router = APIRouter(prefix="/periods", tags=["Accounting Periods"])


def _svc(db: DBSession, user: AuthUser) -> AccountingPeriodService:
    return AccountingPeriodService(
        db, user.tenant_id, user.user_id, getattr(user, "roles", [])
    )


@router.post(
    "/",
    response_model=AccountingPeriodRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new accounting period",
)
async def create_period(
    payload: AccountingPeriodCreate,
    svc: Annotated[AccountingPeriodService, Depends(_svc)],
) -> AccountingPeriodRead:
    period = await svc.create_period(payload)
    return AccountingPeriodRead.model_validate(period)


@router.get(
    "/", response_model=list[AccountingPeriodRead], summary="List accounting periods"
)
async def list_periods(
    svc: Annotated[AccountingPeriodService, Depends(_svc)],
    status: str | None = Query(default=None),
) -> list[AccountingPeriodRead]:
    periods = await svc.list_periods(status=status)
    return [AccountingPeriodRead.model_validate(p) for p in periods]


@router.get(
    "/{period_id}", response_model=AccountingPeriodRead, summary="Get accounting period"
)
async def get_period(
    period_id: uuid.UUID,
    svc: Annotated[AccountingPeriodService, Depends(_svc)],
) -> AccountingPeriodRead:
    return AccountingPeriodRead.model_validate(await svc.get_period(period_id))


@router.post(
    "/{period_id}/soft-close",
    response_model=AccountingPeriodRead,
    summary="Soft-close period (requires treasury_manager role)",
)
async def soft_close(
    period_id: uuid.UUID,
    svc: Annotated[AccountingPeriodService, Depends(_svc)],
    _request: SoftCloseRequest = ...,  # type: ignore[assignment]
) -> AccountingPeriodRead:
    return AccountingPeriodRead.model_validate(await svc.soft_close(period_id))


@router.post(
    "/{period_id}/hard-close",
    response_model=AccountingPeriodRead,
    summary="Hard-close period (requires system_admin role)",
)
async def hard_close(
    period_id: uuid.UUID,
    request: HardCloseRequest,
    svc: Annotated[AccountingPeriodService, Depends(_svc)],
) -> AccountingPeriodRead:
    return AccountingPeriodRead.model_validate(await svc.hard_close(period_id, request))


@router.post(
    "/{period_id}/reopen",
    response_model=AccountingPeriodRead,
    summary="Reopen hard-closed period (requires system_admin role; audit reason mandatory)",
)
async def reopen_period(
    period_id: uuid.UUID,
    request: ReopenRequest,
    svc: Annotated[AccountingPeriodService, Depends(_svc)],
) -> AccountingPeriodRead:
    return AccountingPeriodRead.model_validate(
        await svc.reopen_period(period_id, request)
    )


@router.post(
    "/{period_id}/year-end-rollover",
    summary="Post year-end retained earnings rollover journal",
)
async def year_end_rollover(
    period_id: uuid.UUID,
    request: YearEndRolloverRequest,
    svc: Annotated[AccountingPeriodService, Depends(_svc)],
) -> dict:
    journal_id = await svc.year_end_rollover(request)
    return {"journal_id": str(journal_id)}


@router.get(
    "/ct-dates/calculate",
    response_model=CtTaxDates,
    summary="Calculate CT600 due date and QIP instalment dates for a given period end",
)
async def calculate_ct_dates(
    period_end: date = Query(...),
    is_large_company: bool = Query(default=False),
) -> CtTaxDates:
    return AccountingPeriodService.compute_ct_dates(period_end, is_large_company)
