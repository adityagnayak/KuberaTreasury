from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.dependencies import AuthUser, DBSession
from app.services.auth_service import AuthService, ErasureResponse

router = APIRouter(prefix="/users", tags=["Users"])
svc = AuthService()


@router.delete(
    "/{user_id}/personal-data",
    response_model=ErasureResponse,
    summary="Erase personal data for a user (GDPR right to erasure)",
    description=(
        "Nulls out all PII fields on the user's PersonalDataRecord, sets "
        "is_erased=True and records erased_at.  The user row and all financial "
        "ledger records are untouched.  An immutable audit log entry is written. "
        "Requires the **system_admin** role."
    ),
)
async def erase_personal_data(
    user_id: uuid.UUID, db: DBSession, actor: AuthUser
) -> ErasureResponse:
    """Erase PII for *user_id*.

    Only callers with the **system_admin** role may invoke this endpoint.
    The response payload deliberately omits all erased field values.
    """
    if "system_admin" not in actor.roles:
        raise HTTPException(status_code=403, detail="Forbidden: system_admin role required")

    return await svc.erase_personal_data(db, actor.tenant_id, user_id, actor.user_id)
