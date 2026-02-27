"""
NexusTreasury — Security Layer
AES-256-GCM encryption, JWT creation/verification, password hashing, RBAC dependency.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()

# ─── Password hashing ─────────────────────────────────────────────────────────
# FIX: Switched to pbkdf2_sha256 to avoid bcrypt 72-byte limit issues
_pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    """Return hash of the given plain-text password."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plain password matches the hash."""
    return _pwd_context.verify(plain_password, hashed_password)


# ─── JWT ──────────────────────────────────────────────────────────────────────


def create_access_token(
    subject: str,
    role: str,
    extra: Optional[Dict[str, Any]] = None,
    expires_minutes: Optional[int] = None,
) -> str:
    """
    Create a signed JWT access token.

    :param subject: Usually the user_id.
    :param role: RBAC role string, e.g. 'treasury_analyst'.
    :param extra: Additional claims to embed.
    :param expires_minutes: Override default expiry from settings.
    """
    expiry = expires_minutes or settings.JWT_EXPIRY_MINUTES
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=expiry)

    payload: Dict[str, Any] = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    if extra:
        payload.update(extra)

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode and validate a JWT access token.
    Raises HTTPException 401 on any failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ─── FastAPI dependency ───────────────────────────────────────────────────────


class CurrentUser:
    """Represents the authenticated user extracted from JWT."""

    def __init__(self, user_id: str, role: str, raw_claims: Dict[str, Any]) -> None:
        self.user_id = user_id
        self.role = role
        self.raw_claims = raw_claims

    def __repr__(self) -> str:
        return f"CurrentUser(user_id={self.user_id!r}, role={self.role!r})"


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> CurrentUser:
    """
    FastAPI dependency: extracts and validates the Bearer JWT,
    returning a CurrentUser with user_id and role.
    """
    payload = decode_access_token(credentials.credentials)
    user_id: Optional[str] = payload.get("sub")
    role: Optional[str] = payload.get("role")

    if not user_id or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' or 'role' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(user_id=user_id, role=role, raw_claims=payload)


# ─── AES-256-GCM encryption for bank credentials at rest ─────────────────────


def _get_aes_key() -> bytes:
    """Decode the 32-byte AES key from base64 config."""
    try:
        key_bytes = base64.b64decode(settings.AES_KEY)
    except Exception as exc:
        raise ValueError(f"AES_KEY is not valid base64: {exc}") from exc

    if len(key_bytes) != 32:
        raise ValueError(
            f"AES_KEY must decode to exactly 32 bytes (got {len(key_bytes)}). "
            "Generate with: base64.b64encode(secrets.token_bytes(32)).decode()"
        )
    return key_bytes


def encrypt_credential(plaintext: str) -> str:
    """
    Encrypt a bank credential string using AES-256-GCM.
    Returns a base64-encoded string: nonce(12b) + ciphertext + tag.
    """
    import os

    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)  # 96-bit nonce — unique per encryption
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_credential(encrypted_b64: str) -> str:
    """
    Decrypt a base64-encoded AES-256-GCM credential.
    Raises ValueError on authentication tag failure.
    """
    from cryptography.exceptions import InvalidTag

    key = _get_aes_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(encrypted_b64)
    nonce = raw[:12]
    ciphertext = raw[12:]

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise ValueError("AES-GCM decryption failed — tag mismatch") from exc

    return plaintext.decode("utf-8")
