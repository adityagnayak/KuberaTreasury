"""
User model for authentication.
Add this file to app/models/users.py
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, String, Enum as SAEnum
from sqlalchemy.orm import Mapped

from app.database import Base

# Match the RBAC roles already defined in rbac.py
ROLES = ("system_admin", "treasury_manager", "treasury_analyst", "auditor")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = Column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = Column(String(255), nullable=False)
    full_name: Mapped[str] = Column(String(255), nullable=True)
    role: Mapped[str] = Column(
        SAEnum(*ROLES, name="user_role_enum"), nullable=False, default="treasury_analyst"
    )
    is_active: Mapped[bool] = Column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    last_login: Mapped[datetime] = Column(DateTime(timezone=True), nullable=True)
