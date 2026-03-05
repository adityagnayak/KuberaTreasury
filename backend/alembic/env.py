"""Alembic environment — KuberaTreasury.

Supports both offline (SQL script) and online (live DB) migration modes.
Uses the async psycopg3 driver via run_async_migrations so the same
connection pool configuration works for both the application and migrations.

Run from backend/:
    alembic upgrade head
    alembic downgrade -1
    alembic revision --autogenerate -m "description"
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Application imports ───────────────────────────────────────────────────────
# Import Base first so its metadata is populated, then import every model
# module so SQLAlchemy registers all table definitions before autogenerate
# inspects Base.metadata.

from app.core.database import Base  # noqa: F401  — populates Base.metadata
import app.models  # noqa: F401  — registers all ORM models on Base

from app.core.config import settings

# ── Alembic config object ─────────────────────────────────────────────────────

config = context.config

# Respect the [loggers] / [handlers] / [formatters] blocks in alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Feed the database URL from application settings so credentials never need
# to be duplicated in alembic.ini.
#
# psycopg3 supports both sync and async; alembic uses the sync form for its
# internal operations even when the application uses asyncpg/psycopg-async.
# We swap the async driver variant for the standard sync one here.
_db_url: str = settings.DATABASE_URL.replace(
    "postgresql+psycopg_async://", "postgresql+psycopg://"
)
config.set_main_option("sqlalchemy.url", _db_url)

# Target metadata for --autogenerate support.
target_metadata = Base.metadata


# ── Offline mode ─────────────────────────────────────────────────────────────


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database connection.

    Useful for generating a migration script to review or apply manually.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include schema-level objects (sequences, types) in autogenerate.
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online / async mode ───────────────────────────────────────────────────────


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        # Compare server-default values so autogenerate catches DEFAULT changes.
        compare_server_default=True,
        # Render item-level CHECK constraints in autogenerate output.
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync runner."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
