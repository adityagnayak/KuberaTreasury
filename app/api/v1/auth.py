"""
Auth router — login and current-user endpoints.
Add this file to app/api/v1/auth.py
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    decode_access_token,
)  # your existing functions
from app.database import get_db
from app.services.auth import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


# ── Request / Response schemas ────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    full_name: str | None
    role: str


class MeResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: str
    last_login: datetime | None


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with email + password.
    Returns a JWT access token the frontend stores in memory.
    """
    user = authenticate(db, body.email, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id, user.role)

    return LoginResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
    )


@router.get("/me", response_model=MeResponse)
def me(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
):
    """Return the currently authenticated user's profile."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    # Look up user by ID directly
    from app.models.users import User

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    return MeResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        last_login=user.last_login,
    )
