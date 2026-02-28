"""
Authentication service — uses bcrypt directly (no passlib dependency).
Replaces app/services/auth.py
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.users import User


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_user_by_email(db, email)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return user


def create_user(
    db: Session,
    email: str,
    password: str,
    full_name: str = "",
    role: str = "treasury_analyst",
) -> User:
    user = User(
        email=email.lower().strip(),
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
