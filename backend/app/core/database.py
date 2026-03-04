"""SQLAlchemy 2.0 async-compatible engine and session factory.

Engine and session factory are created lazily on first use so that importing
``Base`` (e.g. in the test suite) never requires a live database driver.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


_engine = None
_AsyncSessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        from app.core.config import settings  # deferred to avoid import-time side-effects
        _engine = create_async_engine(
            settings.DATABASE_URL,
            pool_size=settings.DATABASE_POOL_SIZE,
            max_overflow=settings.DATABASE_MAX_OVERFLOW,
            echo=settings.APP_ENV == "development",
        )
    return _engine


def _get_session_factory():
    global _AsyncSessionLocal
    if _AsyncSessionLocal is None:
        _AsyncSessionLocal = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
