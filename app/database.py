"""
NexusTreasury — Database Engine & Session Factory
Supports SQLite (local dev) and PostgreSQL (production).
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base — all ORM models inherit from this."""

    pass


def _build_engine(database_url: str) -> Engine:
    """Construct SQLAlchemy engine with appropriate settings for URL type."""
    is_sqlite = database_url.startswith("sqlite")

    if is_sqlite:
        # SQLite uses SingletonThreadPool — pool_size/max_overflow are not supported
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            echo=False,
        )

        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    else:
        # PostgreSQL / other relational DBs
        engine = create_engine(
            database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=False,
        )

    return engine


# Build the engine once at import time
settings = get_settings()
engine: Engine = _build_engine(settings.DATABASE_URL)

# Session factory
SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a SQLAlchemy Session.
    Automatically closes the session after the request.

    Usage:
        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Create all tables defined in all model modules.
    Call this on application startup.
    """
    # Import all models so their table definitions are registered on Base.metadata
    from app.models import (  # noqa: F401
        entities,
        forecasts,
        instruments,
        mandates,
        payments,
        transactions,
    )

    Base.metadata.create_all(bind=engine)

    # Install SQLite triggers (no-op on PostgreSQL)
    if settings.is_sqlite:
        _install_sqlite_triggers()


def _install_sqlite_triggers() -> None:
    """Install SQLite-specific audit and immutability triggers."""
    from app.models.transactions import SQLITE_TRIGGERS

    with engine.connect() as conn:
        for stmt in SQLITE_TRIGGERS.strip().split(";\n\n"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(text(stmt))
                except Exception as exc:
                    if "already exists" not in str(exc).lower():
                        raise
        conn.commit()
