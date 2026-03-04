"""Pytest fixtures shared across the KuberaTreasury test suite.

Uses an in-memory SQLite database (via aiosqlite) so tests require no running
PostgreSQL instance.  PostgreSQL-specific DDL (triggers, enums) is bypassed
by using SQLAlchemy's ``create_all`` against a clean SQLite engine.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import AsyncIterator

import pytest
import pytest_asyncio
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


async def _init_engine():
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
            connect_args={"check_same_thread": False},
        )
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine, _session_factory


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """Provide a fresh transactional session, rolled back after each test."""
    eng, factory = await _init_engine()
    async with factory() as session:
        yield session
        await session.rollback()


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

