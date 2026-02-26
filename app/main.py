"""
NexusTreasury — FastAPI Application Entry Point
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# FIX: Imports moved to top to satisfy E402
from app.api.v1 import accounts, forecasts, instruments, payments, positions, reports
from app.config import get_settings
from app.core.exceptions import NexusTreasuryError

settings = get_settings()


# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB tables on startup."""
    from app.database import init_db

    init_db()
    yield


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    description=(
        "NexusTreasury — Production-grade Treasury Management System. "
        "Phases 1-5: Statement ingestion, cash positioning, payment factory, "
        "FX risk management, E-BAM, and full RBAC."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ─── CORS ─────────────────────────────────────────────────────────────────────

origins = settings.ALLOWED_ORIGINS if settings.is_production else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Exception handlers ───────────────────────────────────────────────────────


@app.exception_handler(NexusTreasuryError)
async def nexus_exception_handler(
    request: Request, exc: NexusTreasuryError
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if settings.ENVIRONMENT == "development":
        import traceback

        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "An internal error occurred.",
        },
    )


# ─── Health endpoint ──────────────────────────────────────────────────────────


@app.get("/health", tags=["health"])
async def health_check() -> Dict[str, Any]:
    """
    Returns system health including DB and cache connectivity.
    Used by Railway / load balancer health checks.
    """
    db_ok = False
    cache_ok = False

    try:
        from app.database import engine

        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        from app.cache.fx_cache import get_redis_client

        redis = get_redis_client()
        redis.set("__health_check__", "1")
        cache_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "db_connected": db_ok,
        "cache_connected": cache_ok,
    }


# ─── Routers ──────────────────────────────────────────────────────────────────

API_PREFIX = "/api/v1"

app.include_router(accounts.router, prefix=API_PREFIX)
app.include_router(payments.router, prefix=API_PREFIX)
app.include_router(positions.router, prefix=API_PREFIX)
app.include_router(forecasts.router, prefix=API_PREFIX)
app.include_router(instruments.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)
