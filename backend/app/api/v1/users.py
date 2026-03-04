from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.core.dependencies import AuthUser, DBSession
from app.services.auth_service import AuthService, ErasureResponse

router = APIRouter(prefix="/users", tags=["Users"])
svc = AuthService()


@router.delete("/{user_id}/personal-data", response_model=ErasureResponse)
async def erase_personal_data(user_id: uuid.UUID, db: DBSession, actor: AuthUser) -> ErasureResponse:
    if actor.user_id != user_id and "system_admin" not in actor.roles and "cfo" not in actor.roles:
        raise HTTPException(status_code=403, detail="Forbidden")
    return await svc.erase_personal_data(db, actor.tenant_id, user_id, actor.user_id)
