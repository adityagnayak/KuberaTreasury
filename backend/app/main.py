"""KuberaTreasury — FastAPI application entry point.

Security headers (OWASP), CORS, JWT bearer scheme, per-module routers.
The exception handler translates every ``KuberaError`` subclass to its
HTTP status code and RFC 7807-style JSON body.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.exceptions import KuberaError
from app.api.v1.chart_of_accounts import router as coa_router
from app.api.v1.ledger import router as ledger_router
from app.api.v1.hedges import router as hedge_router
from app.api.v1.fx_revaluation import router as fx_router
from app.api.v1.intercompany import router as ic_router
from app.api.v1.accounting_period import router as period_router


# ─────────────────────────────────────────────────── Security headers ──────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none';"
        )
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


# ─────────────────────────────────────────────────── Application factory ───────

def create_app() -> FastAPI:
    app = FastAPI(
        title="KuberaTreasury API",
        version="2.0.0",
        description=(
            "UK Treasury Management System — IFRS 9, HMRC CIR, FRS 101/102, "
            "IAS 21, CT600, ISAE 3402 compliant."
        ),
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.APP_ENV != "production" else None,
    )

    # Middleware
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=getattr(settings, "ALLOWED_ORIGINS", ["http://localhost:5173"]),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # Exception handler — converts KuberaError → RFC 7807 JSON
    @app.exception_handler(KuberaError)
    async def kubera_error_handler(request: Request, exc: KuberaError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://kuberatreasury.com/errors/{exc.__class__.__name__}",
                "title": exc.__class__.__name__,
                "status": exc.status_code,
                "detail": str(exc),
            },
        )

    # Routers — all under /api/v1
    API_PREFIX = "/api/v1"
    app.include_router(coa_router, prefix=API_PREFIX)
    app.include_router(ledger_router, prefix=API_PREFIX)
    app.include_router(hedge_router, prefix=API_PREFIX)
    app.include_router(fx_router, prefix=API_PREFIX)
    app.include_router(ic_router, prefix=API_PREFIX)
    app.include_router(period_router, prefix=API_PREFIX)

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        return {"status": "ok", "version": app.version}

    return app


app = create_app()
