"""FX Revaluation — FastAPI v1 router."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import AuthUser, DBSession
from app.services.fx_revaluation_service import (
    FxRevaluationService,
    HmrcRateIngest,
    HmrcRateRead,
    RevaluationReport,
    RevaluationRequest,
)

router = APIRouter(prefix="/fx", tags=["FX Revaluation"])


def _svc(db: DBSession, user: AuthUser) -> FxRevaluationService:
    return FxRevaluationService(db, user.tenant_id, user.user_id)


@router.post(
    "/rates/ingest",
    response_model=list[HmrcRateRead],
    status_code=status.HTTP_201_CREATED,
    summary="Manually ingest HMRC exchange rates (for testing or overrides)",
)
async def ingest_rates(
    rates: list[HmrcRateIngest],
    svc: Annotated[FxRevaluationService, Depends(_svc)],
) -> list[HmrcRateRead]:
    rows = await svc.ingest_rates(rates)
    return [HmrcRateRead.model_validate(r) for r in rows]


@router.post(
    "/rates/fetch/{period_end}",
    response_model=list[HmrcRateRead],
    summary="Fetch HMRC monthly exchange rates for period end date and ingest",
)
async def fetch_hmrc_rates(
    period_end: date,
    svc: Annotated[FxRevaluationService, Depends(_svc)],
) -> list[HmrcRateRead]:
    rows = await svc.fetch_and_ingest_hmrc_rates(period_end)
    return [HmrcRateRead.model_validate(r) for r in rows]


@router.get("/rates", response_model=list[HmrcRateRead], summary="List ingested HMRC exchange rates")
async def list_rates(
    svc: Annotated[FxRevaluationService, Depends(_svc)],
    published_date: date | None = Query(default=None),
    currency_code: str | None = Query(default=None),
) -> list[HmrcRateRead]:
    rows = await svc.list_rates(published_date=published_date, currency_code=currency_code)
    return [HmrcRateRead.model_validate(r) for r in rows]


@router.post(
    "/revalue",
    response_model=RevaluationReport,
    status_code=status.HTTP_201_CREATED,
    summary="Run period-end FX revaluation using HMRC rates and post gain/loss journal",
)
async def revalue_period_end(
    request: RevaluationRequest,
    svc: Annotated[FxRevaluationService, Depends(_svc)],
) -> RevaluationReport:
    return await svc.revalue_period_end(request)
