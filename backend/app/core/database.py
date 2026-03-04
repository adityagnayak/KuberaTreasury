"""SQLAlchemy 2.0 async-compatible engine and session factory.

Engine and session factory are created lazily on first use so that importing
``Base`` (e.g. in the test suite) never requires a live database driver.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
import contextvars
import uuid

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy import event
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


_engine = None
_AsyncSessionLocal = None
tenant_context: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar("tenant_context", default=None)


def set_tenant_context(tenant_id: uuid.UUID | None) -> contextvars.Token:
    return tenant_context.set(tenant_id)


def reset_tenant_context(token: contextvars.Token) -> None:
    tenant_context.reset(token)


@event.listens_for(Session, "do_orm_execute")
def _tenant_filter(execute_state):
    tenant_id = tenant_context.get()
    if tenant_id is None:
        return
    if not execute_state.is_select:
        return

    mapper_classes = [m.class_ for m in Base.registry.mappers if hasattr(m.class_, "tenant_id")]
    statement = execute_state.statement
    for cls in mapper_classes:
        statement = statement.options(
            with_loader_criteria(cls, lambda model: model.tenant_id == tenant_id, include_aliases=True)
        )
    execute_state.statement = statement


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
