"""AES-256-GCM field-level encryption for PII stored at rest.

Usage::

    from app.security.encryption import encrypt_field, decrypt_field, EncryptedString

``EncryptedString`` is a SQLAlchemy ``TypeDecorator`` that transparently
encrypts on write and decrypts on read, keeping plain-text PII off disk.

Key material is sourced from ``settings.PII_ENCRYPTION_KEY`` (a hex-encoded
32-byte / 256-bit value).  If the key is absent (e.g. unit-test environments)
a deterministic all-zero key is used — this must be overridden in production
via the ``PII_ENCRYPTION_KEY`` environment variable.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def _get_key() -> bytes:
    """Return a 32-byte AES key derived from configuration.

    In production, set ``PII_ENCRYPTION_KEY`` to a hex-encoded 32-byte value.
    The helper SHA-256 hashes whatever string is provided so that any key
    length is accepted, producing a stable 32-byte result.
    """
    # Lazy import to avoid circular imports at module load time.
    from app.core.config import settings  # noqa: PLC0415

    raw: str | None = getattr(settings, "PII_ENCRYPTION_KEY", None)
    if not raw:
        # Deterministic zero key – safe for tests, insecure for production.
        return b"\x00" * 32
    return hashlib.sha256(raw.encode("utf-8")).digest()


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def encrypt_field(plaintext: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM; return base64-encoded blob.

    The 12-byte random nonce is prepended to the ciphertext so each call
    produces a different output even for the same input.
    """
    key = _get_key()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_field(token: str) -> str:
    """Decrypt a blob produced by :func:`encrypt_field`."""
    key = _get_key()
    raw = base64.b64decode(token)
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


# ---------------------------------------------------------------------------
# SQLAlchemy TypeDecorator
# ---------------------------------------------------------------------------

class EncryptedString(TypeDecorator):
    """Transparent AES-256-GCM encryption for a SQLAlchemy ``Text`` column.

    Values are encrypted before being persisted and decrypted after being
    fetched.  ``None`` is stored and returned as ``None`` (not encrypted).
    A ``ValueError`` / ``Exception`` during decryption (e.g. corrupt data
    after erasure) returns ``None`` silently.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        if value is None:
            return None
        return encrypt_field(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        if value is None:
            return None
        try:
            return decrypt_field(value)
        except Exception:
            # Data was erased or is corrupt — surface as None.
            return None
