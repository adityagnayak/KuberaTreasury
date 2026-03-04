"""Ledger journal — FastAPI v1 router."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status

from app.core.dependencies import AuthUser, DBSession
from app.services.ledger_service import (
    JournalCreate,
    JournalRead,
    LedgerService,
    RecurringTemplateCreate,
)

router = APIRouter(prefix="/ledger", tags=["Ledger"])


def _svc(
    db: DBSession,
    user: AuthUser,
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> LedgerService:
    return LedgerService(
        db, user.tenant_id, user.user_id, user_ip=x_forwarded_for or ""
    )


@router.post(
    "/journals",
    response_model=JournalRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft journal (double-entry validated)",
)
async def create_journal(
    payload: JournalCreate,
    svc: Annotated[LedgerService, Depends(_svc)],
) -> JournalRead:
    jnl = await svc.create_journal(payload)
    return JournalRead.model_validate(jnl)


@router.post(
    "/journals/{journal_id}/post",
    response_model=JournalRead,
    summary="Post a draft journal to the ledger",
)
async def post_journal(
    journal_id: uuid.UUID,
    svc: Annotated[LedgerService, Depends(_svc)],
) -> JournalRead:
    jnl = await svc.post_journal(journal_id)
    return JournalRead.model_validate(jnl)


@router.post(
    "/journals/{journal_id}/reverse",
    response_model=JournalRead,
    status_code=status.HTTP_201_CREATED,
    summary="Reverse a posted journal into an open period",
)
async def reverse_journal(
    journal_id: uuid.UUID,
    target_period_id: uuid.UUID,
    svc: Annotated[LedgerService, Depends(_svc)],
    description: str | None = None,
) -> JournalRead:
    rev = await svc.reverse_journal(journal_id, target_period_id, description)
    return JournalRead.model_validate(rev)


@router.get("/journals", response_model=list[JournalRead], summary="List journals")
async def list_journals(
    svc: Annotated[LedgerService, Depends(_svc)],
    period_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
) -> list[JournalRead]:
    journals = await svc.list_journals(
        period_id=period_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [JournalRead.model_validate(j) for j in journals]


@router.get(
    "/journals/{journal_id}",
    response_model=JournalRead,
    summary="Get journal with lines",
)
async def get_journal(
    journal_id: uuid.UUID,
    svc: Annotated[LedgerService, Depends(_svc)],
) -> JournalRead:
    return JournalRead.model_validate(await svc.get_journal(journal_id))


# ── Recurring templates ────────────────────────────────────────────────────────


@router.post(
    "/recurring-templates",
    status_code=status.HTTP_201_CREATED,
    summary="Create a recurring journal template",
)
async def create_recurring_template(
    payload: RecurringTemplateCreate,
    svc: Annotated[LedgerService, Depends(_svc)],
) -> dict:
    tmpl = await svc.create_recurring_template(payload)
    return {"template_id": str(tmpl.template_id), "template_name": tmpl.template_name}


@router.post(
    "/recurring-templates/run",
    summary="Materialise all due recurring journals for a period",
)
async def run_recurring(
    period_id: uuid.UUID,
    as_of: str,  # YYYY-MM-DD
    svc: Annotated[LedgerService, Depends(_svc)],
) -> dict:
    from datetime import date as _date

    journals = await svc.run_due_recurring(period_id, _date.fromisoformat(as_of))
    return {
        "journals_created": len(journals),
        "journal_ids": [str(j.journal_id) for j in journals],
    }
