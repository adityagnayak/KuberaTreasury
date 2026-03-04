"""Tests for app.security.encryption — AES-256-GCM field-level encryption.

Covers every branch of encrypt_field, decrypt_field, _get_key, and the
EncryptedString SQLAlchemy TypeDecorator including the previously-uncovered
zero-key fallback (line 44) and the corrupt-data silent-except (lines 97-99).
"""

from __future__ import annotations

import base64
import importlib
import os
from unittest.mock import patch

import pytest

from app.security.encryption import (
    EncryptedString,
    decrypt_field,
    encrypt_field,
    _get_key,
)


# ═════════════════════════════════════════════════════════════════════════════
# _get_key
# ═════════════════════════════════════════════════════════════════════════════


def test_get_key_returns_32_bytes() -> None:
    """_get_key always returns exactly 32 bytes."""
    key = _get_key()
    assert isinstance(key, bytes)
    assert len(key) == 32


def test_get_key_zero_key_when_pii_encryption_key_absent(monkeypatch) -> None:
    """When PII_ENCRYPTION_KEY is not set the fallback must be 32 zero bytes."""
    monkeypatch.setenv("PII_ENCRYPTION_KEY", "")
    # Force settings reload so env change is picked up.
    import app.core.config as cfg_mod  # noqa: PLC0415

    with patch.object(cfg_mod.settings, "PII_ENCRYPTION_KEY", None):
        key = _get_key()
    assert key == b"\x00" * 32


def test_get_key_derives_fixed_32_bytes_from_non_empty_value(monkeypatch) -> None:
    """A non-empty PII_ENCRYPTION_KEY produces a deterministic 32-byte key."""
    import hashlib  # noqa: PLC0415

    secret = "my-test-secret-value"
    expected = hashlib.sha256(secret.encode("utf-8")).digest()

    import app.core.config as cfg_mod  # noqa: PLC0415

    with patch.object(cfg_mod.settings, "PII_ENCRYPTION_KEY", secret):
        key = _get_key()
    assert key == expected
    assert len(key) == 32


def test_get_key_same_input_same_output(monkeypatch) -> None:
    """_get_key is deterministic for the same PII_ENCRYPTION_KEY value."""
    import app.core.config as cfg_mod  # noqa: PLC0415

    with patch.object(cfg_mod.settings, "PII_ENCRYPTION_KEY", "stable-key"):
        key1 = _get_key()
        key2 = _get_key()
    assert key1 == key2


# ═════════════════════════════════════════════════════════════════════════════
# encrypt_field / decrypt_field
# ═════════════════════════════════════════════════════════════════════════════


def test_encrypt_returns_base64_string() -> None:
    token = encrypt_field("hello world")
    # Must be valid base64.
    decoded = base64.b64decode(token)
    # 12-byte nonce + at least 1 byte ciphertext + 16-byte GCM tag minimum
    assert len(decoded) >= 12 + 1 + 16


def test_roundtrip_ascii() -> None:
    plaintext = "jane.smith@example.com"
    assert decrypt_field(encrypt_field(plaintext)) == plaintext


def test_roundtrip_unicode() -> None:
    plaintext = "André Müller — 日本語テスト"
    assert decrypt_field(encrypt_field(plaintext)) == plaintext


def test_roundtrip_empty_string() -> None:
    assert decrypt_field(encrypt_field("")) == ""


def test_roundtrip_long_address() -> None:
    addr = "1 Very Long Street Name, Apartment 42B, London, Greater London, EC1A 9ZZ, United Kingdom"
    assert decrypt_field(encrypt_field(addr)) == addr


def test_different_calls_produce_different_ciphertexts() -> None:
    """Random nonce means same plaintext → different ciphertext each time."""
    t1 = encrypt_field("same input")
    t2 = encrypt_field("same input")
    assert t1 != t2, "Ciphertexts must differ due to random nonces"


def test_decrypt_rejects_tampered_ciphertext() -> None:
    """Tampering with the ciphertext must raise an exception (GCM auth tag fails)."""
    from cryptography.exceptions import InvalidTag  # noqa: PLC0415

    token = encrypt_field("sensitive data")
    raw = bytearray(base64.b64decode(token))
    raw[-1] ^= 0xFF  # flip last byte of auth tag
    tampered = base64.b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(Exception):  # InvalidTag or similar
        decrypt_field(tampered)


def test_wrong_key_cannot_decrypt(monkeypatch) -> None:
    """Ciphertext encrypted with key-A cannot be decrypted with key-B."""
    import app.core.config as cfg_mod  # noqa: PLC0415

    with patch.object(cfg_mod.settings, "PII_ENCRYPTION_KEY", "key-A"):
        token = encrypt_field("secret")
    with patch.object(cfg_mod.settings, "PII_ENCRYPTION_KEY", "key-B"):
        with pytest.raises(Exception):
            decrypt_field(token)


# ═════════════════════════════════════════════════════════════════════════════
# EncryptedString TypeDecorator — process_bind_param
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def enc() -> EncryptedString:
    return EncryptedString()


def test_bind_none_returns_none(enc: EncryptedString) -> None:
    assert enc.process_bind_param(None, dialect=None) is None


def test_bind_encrypts_non_none(enc: EncryptedString) -> None:
    result = enc.process_bind_param("jane@example.com", dialect=None)
    assert result is not None
    assert result != "jane@example.com"
    # Must be valid base64.
    base64.b64decode(result)


def test_bind_roundtrips_via_result(enc: EncryptedString) -> None:
    stored = enc.process_bind_param("+44 7700 900000", dialect=None)
    recovered = enc.process_result_value(stored, dialect=None)
    assert recovered == "+44 7700 900000"


# ═════════════════════════════════════════════════════════════════════════════
# EncryptedString TypeDecorator — process_result_value
# ═════════════════════════════════════════════════════════════════════════════


def test_result_none_returns_none(enc: EncryptedString) -> None:
    assert enc.process_result_value(None, dialect=None) is None


def test_result_decrypts_valid_token(enc: EncryptedString) -> None:
    token = encrypt_field("1 Treasury Lane")
    assert enc.process_result_value(token, dialect=None) == "1 Treasury Lane"


def test_result_corrupt_data_returns_none(enc: EncryptedString) -> None:
    """Corrupt / erased ciphertext must be silently treated as None (not raise)."""
    garbage = base64.b64encode(b"\xde\xad\xbe\xef" * 10).decode("ascii")
    assert enc.process_result_value(garbage, dialect=None) is None


def test_result_tampered_token_returns_none(enc: EncryptedString) -> None:
    """A token whose GCM auth tag has been mutated must return None silently."""
    token = encrypt_field("valid data")
    raw = bytearray(base64.b64decode(token))
    raw[-1] ^= 0xFF
    tampered = base64.b64encode(bytes(raw)).decode("ascii")
    assert enc.process_result_value(tampered, dialect=None) is None


def test_result_empty_string_token_returns_none(enc: EncryptedString) -> None:
    """A completely empty stored value must not raise."""
    assert enc.process_result_value("", dialect=None) is None


# ═════════════════════════════════════════════════════════════════════════════
# cache_ok attribute
# ═════════════════════════════════════════════════════════════════════════════


def test_encrypted_string_cache_ok() -> None:
    """EncryptedString.cache_ok must be True (required by SQLAlchemy)."""
    assert EncryptedString.cache_ok is True
