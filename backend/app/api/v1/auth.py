from __future__ import annotations

import uuid

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings
from app.core.dependencies import AuthUser, DBSession
from app.services.auth_service import (
    AuthService,
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["Auth"])
svc = AuthService()


class MfaVerifyRequest(BaseModel):
    code: str


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DBSession
) -> TokenResponse:
    try:
        token, refresh_token, _meta = await svc.login(
            db,
            payload,
            request.client.host if request.client else None,
            request.headers.get("user-agent"),
        )
        response.set_cookie(
            key=settings.JWT_REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=settings.APP_ENV == "production",
            samesite="lax",
            max_age=settings.JWT_REFRESH_TOKEN_TTL_DAYS * 24 * 3600,
        )
        return token
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    db: DBSession,
    refresh_token: str | None = Cookie(
        default=None, alias=settings.JWT_REFRESH_COOKIE_NAME
    ),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )
    try:
        payload = jwt.decode(
            refresh_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    try:
        return await svc.refresh_access_token(
            db,
            payload,
            request.client.host if request.client else None,
            request.headers.get("user-agent"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post("/mfa/setup")
async def mfa_setup(db: DBSession, user: AuthUser) -> dict:
    email = f"{user.user_id}@tenant.local"
    result = await svc.setup_mfa(db, user.tenant_id, user.user_id, email)
    return result.model_dump()


@router.post("/mfa/verify")
async def mfa_verify(payload: MfaVerifyRequest, db: DBSession, user: AuthUser) -> dict:
    ok = await svc.verify_mfa_setup(
        db, user.tenant_id, user.user_id, payload.code, user.roles
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    return {"verified": True}


@router.post("/logout-all")
async def logout_all(db: DBSession, user: AuthUser) -> dict:
    revoked = await svc.revoke_all_sessions(
        db, user.tenant_id, user.user_id, user.user_id
    )
    return {"revoked_sessions": revoked}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest, db: DBSession, user: AuthUser
) -> dict:
    try:
        await svc.change_password(db, user.tenant_id, user.user_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"changed": True}
