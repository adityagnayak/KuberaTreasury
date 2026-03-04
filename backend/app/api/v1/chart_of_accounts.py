"""Chart of Accounts — FastAPI v1 router."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import AuthUser, DBSession
from app.services.chart_of_accounts_service import (
    AccountCreate,
    AccountRead,
    AccountUpdate,
    ChartOfAccountsService,
)

router = APIRouter(prefix="/chart-of-accounts", tags=["Chart of Accounts"])


def _svc(db: DBSession, user: AuthUser) -> ChartOfAccountsService:
    return ChartOfAccountsService(db, user.tenant_id)


@router.post(
    "/seed",
    response_model=list[AccountRead],
    status_code=status.HTTP_201_CREATED,
    summary="Seed the UK standard chart of accounts for this tenant",
)
async def seed_uk_standard(
    svc: Annotated[ChartOfAccountsService, Depends(_svc)],
) -> list[AccountRead]:
    accounts = await svc.seed_uk_standard()
    return [AccountRead.model_validate(a) for a in accounts]


@router.post(
    "/",
    response_model=AccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new GL account",
)
async def create_account(
    payload: AccountCreate,
    svc: Annotated[ChartOfAccountsService, Depends(_svc)],
) -> AccountRead:
    account = await svc.create(payload)
    return AccountRead.model_validate(account)


@router.get("/", response_model=list[AccountRead], summary="List accounts")
async def list_accounts(
    svc: Annotated[ChartOfAccountsService, Depends(_svc)],
    account_type: str | None = Query(default=None),
    is_treasury: bool | None = Query(default=None),
    active_only: bool = Query(default=True),
) -> list[AccountRead]:
    accounts = await svc.list_all(
        account_type=account_type,
        is_treasury=is_treasury,
        active_only=active_only,
    )
    return [AccountRead.model_validate(a) for a in accounts]


@router.get("/{account_id}", response_model=AccountRead, summary="Get account by ID")
async def get_account(
    account_id: uuid.UUID,
    svc: Annotated[ChartOfAccountsService, Depends(_svc)],
) -> AccountRead:
    return AccountRead.model_validate(await svc.get(account_id))


@router.patch("/{account_id}", response_model=AccountRead, summary="Update account metadata")
async def update_account(
    account_id: uuid.UUID,
    payload: AccountUpdate,
    svc: Annotated[ChartOfAccountsService, Depends(_svc)],
) -> AccountRead:
    return AccountRead.model_validate(await svc.update(account_id, payload))


@router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate (soft-delete) an account",
)
async def deactivate_account(
    account_id: uuid.UUID,
    svc: Annotated[ChartOfAccountsService, Depends(_svc)],
) -> None:
    await svc.deactivate(account_id)
