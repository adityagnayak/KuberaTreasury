"""Pytest fixtures shared across the KuberaTreasury test suite.

Defaults to in-memory SQLite for local runs, but honors ``DATABASE_URL`` when
provided (e.g. CI PostgreSQL service) so the same suite can run against
PostgreSQL.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.database import Base
from app.models import (
    AccountingPeriod,
    ChartOfAccount,
    Tenant,
)

# ─────────────────────────────────────────────────── DB fixtures ───────────────

_engine = None
_session_factory = None


if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _init_engine():
    global _engine, _session_factory
    if _engine is None:
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        is_sqlite = database_url.startswith("sqlite+")

        engine_kwargs = {"echo": False}
        if is_sqlite:
            engine_kwargs["connect_args"] = {"check_same_thread": False}

        _engine = create_async_engine(
            database_url,
            **engine_kwargs,
        )

        if is_sqlite:
            @event.listens_for(_engine.sync_engine, "connect")
            def _sqlite_functions(dbapi_conn, _record):
                dbapi_conn.create_function(
                    "now", 0, lambda: datetime.utcnow().isoformat(sep=" ")
                )

        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _session_factory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine, _session_factory


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Provide an isolated transactional session per test.

    A connection-level transaction is always rolled back, so even explicit
    ``session.commit()`` calls inside tests never leak state to other tests.
    """
    eng, _ = await _init_engine()
    async with eng.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


# ─────────────────────────────────────────────────── Domain fixtures ───────────


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest_asyncio.fixture
async def tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    t = Tenant(
        tenant_id=tenant_id,
        tenant_name="Test Corp Ltd",
        company_number="12345678",
        vrn="123456789",
    )
    db.add(t)
    await db.flush()
    return t


@pytest_asyncio.fixture
async def base_account(db: AsyncSession, tenant_id: uuid.UUID) -> ChartOfAccount:
    acct = ChartOfAccount(
        tenant_id=tenant_id,
        account_code="1000",
        account_name="Cash",
        account_type="asset",
        currency_code="GBP",
        is_active=True,
        allows_currency_revaluation=False,
    )
    db.add(acct)
    await db.flush()
    return acct


@pytest_asyncio.fixture
async def counter_account(db: AsyncSession, tenant_id: uuid.UUID) -> ChartOfAccount:
    acct = ChartOfAccount(
        tenant_id=tenant_id,
        account_code="4000",
        account_name="Revenue",
        account_type="income",
        currency_code="GBP",
        is_active=True,
        allows_currency_revaluation=False,
    )
    db.add(acct)
    await db.flush()
    return acct


@pytest_asyncio.fixture
async def open_period(db: AsyncSession, tenant_id: uuid.UUID) -> AccountingPeriod:
    p = AccountingPeriod(
        tenant_id=tenant_id,
        period_name="Jan 2026",
        period_type="monthly",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        is_year_end=False,
        is_large_company_for_ct=False,
        status="open",
    )
    db.add(p)
    await db.flush()
    return p
