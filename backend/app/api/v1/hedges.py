"""Hedge Accounting — FastAPI v1 router (IFRS 9)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.dependencies import AuthUser, DBSession
from app.services.hedge_service import (
    DeDesignationUpdate,
    EffectivenessTestCreate,
    EffectivenessTestRead,
    HedgeAccountingService,
    HedgeDesignationCreate,
    HedgeDesignationRead,
    OciReclassificationCreate,
)

router = APIRouter(prefix="/hedges", tags=["Hedge Accounting (IFRS 9)"])


def _svc(db: DBSession, user: AuthUser) -> HedgeAccountingService:
    return HedgeAccountingService(db, user.tenant_id, user.user_id)


@router.post(
    "/",
    response_model=HedgeDesignationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Designate a new hedge relationship (IFRS 9 §6.2)",
)
async def designate_hedge(
    payload: HedgeDesignationCreate,
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
) -> HedgeDesignationRead:
    return HedgeDesignationRead.model_validate(await svc.designate(payload))


@router.get(
    "/", response_model=list[HedgeDesignationRead], summary="List hedge designations"
)
async def list_hedges(
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
    active_only: bool = True,
) -> list[HedgeDesignationRead]:
    hedges = await svc.list_designations(active_only=active_only)
    return [HedgeDesignationRead.model_validate(h) for h in hedges]


@router.get(
    "/{hedge_id}", response_model=HedgeDesignationRead, summary="Get hedge designation"
)
async def get_hedge(
    hedge_id: uuid.UUID,
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
) -> HedgeDesignationRead:
    return HedgeDesignationRead.model_validate(await svc.get_designation(hedge_id))


@router.post(
    "/{hedge_id}/effectiveness",
    response_model=EffectivenessTestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run period-end effectiveness test (IFRS 9 §B6.4)",
)
async def run_effectiveness_test(
    hedge_id: uuid.UUID,
    payload: EffectivenessTestCreate,
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
) -> EffectivenessTestRead:
    result = await svc.run_effectiveness_test(hedge_id, payload)
    return EffectivenessTestRead.model_validate(result)


@router.get(
    "/{hedge_id}/effectiveness",
    response_model=list[EffectivenessTestRead],
    summary="List all effectiveness tests for a hedge",
)
async def list_effectiveness_tests(
    hedge_id: uuid.UUID,
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
) -> list[EffectivenessTestRead]:
    tests = await svc.list_effectiveness_tests(hedge_id)
    return [EffectivenessTestRead.model_validate(t) for t in tests]


@router.post(
    "/{hedge_id}/oci-reclassification",
    status_code=status.HTTP_201_CREATED,
    summary="Reclassify cumulative OCI to P&L when hedged item affects profit/loss (IFRS 9 §6.5.11)",
)
async def reclassify_oci(
    hedge_id: uuid.UUID,
    payload: OciReclassificationCreate,
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
) -> dict:
    rec = await svc.reclassify_oci_to_pnl(hedge_id, payload)
    return {
        "oci_reclassification_id": str(rec.oci_reclassification_id),
        "amount_reclassified": str(rec.amount_reclassified),
        "journal_id": str(rec.journal_id),
    }


@router.post(
    "/{hedge_id}/de-designate",
    response_model=HedgeDesignationRead,
    summary="De-designate hedge — records reason and cumulative OCI treatment (IFRS 9 §6.5.6)",
)
async def de_designate(
    hedge_id: uuid.UUID,
    payload: DeDesignationUpdate,
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
) -> HedgeDesignationRead:
    return HedgeDesignationRead.model_validate(
        await svc.de_designate(hedge_id, payload)
    )


@router.get(
    "/register/export",
    summary="Export hedge register (JSON payload for PDF auditor pack)",
)
async def export_hedge_register(
    svc: Annotated[HedgeAccountingService, Depends(_svc)],
) -> list[dict]:
    return await svc.get_hedge_register()
