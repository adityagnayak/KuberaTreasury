"""FastAPI dependency injectors — auth, tenant, session."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db

# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------
DBSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Current user / tenant extraction from JWT
# ---------------------------------------------------------------------------
class CurrentUser:
    def __init__(
        self, user_id: uuid.UUID, tenant_id: uuid.UUID, roles: list[str]
    ) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.roles = roles


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not authorization or not authorization.startswith("Bearer "):
        raise credentials_exc
    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str | None = payload.get("sub")
        tenant_id: str | None = payload.get("tenant_id")
        roles: list[str] = payload.get("roles", [])
        token_type: str | None = payload.get("type")
        if token_type != "access" or not user_id or not tenant_id:
            raise credentials_exc
        return CurrentUser(
            user_id=uuid.UUID(user_id),
            tenant_id=uuid.UUID(tenant_id),
            roles=roles,
        )
    except (JWTError, ValueError):
        raise credentials_exc


AuthUser = Annotated[CurrentUser, Depends(get_current_user)]
