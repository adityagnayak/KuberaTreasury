"""User-linked PII model.

``PersonalDataRecord`` is the *only* place where personally identifiable
information is stored.  Financial ledger tables (journals, payments, etc.)
must never store PII directly — they reference the user by ``user_id`` UUID
only.  All sensitive string fields are encrypted at rest using AES-256-GCM
via :class:`app.security.encryption.EncryptedString`.

GDPR / UK-GDPR "right to erasure" is implemented by:
  1. Nulling out all PII fields.
  2. Setting ``is_erased = True`` and ``erased_at = now()``.
  3. Retaining the row so that the erasure audit trail is preserved.
  4. Never deleting the associated ``users`` row or any ledger records.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.security.encryption import EncryptedString


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class PersonalDataRecord(Base):
    """One-to-one PII store for a user, separated from the financial ledger.

    Fields
    ------
    id          Primary key (UUID).
    tenant_id   FK to ``tenants``, indexed for multi-tenant queries.
    user_id     FK to ``users``, unique — one PII record per user.
    full_name   Encrypted at rest with AES-256-GCM.
    email       Encrypted at rest with AES-256-GCM.
    phone       Encrypted at rest with AES-256-GCM.
    address     Encrypted at rest with AES-256-GCM.
    created_at  Immutable creation timestamp.
    erased_at   Set on erasure; null while record is live.
    is_erased   True once GDPR erasure has been performed.
    """

    __tablename__ = "personal_data_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )

    # PII — all nullable so erasure can null them out without removing the row.
    full_name: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    email: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    phone: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    address: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    erased_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_erased: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
