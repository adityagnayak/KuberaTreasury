"""KuberaTreasury — FastAPI application entry point.

Security headers (OWASP), CORS, JWT bearer scheme, per-module routers.
The exception handler translates every ``KuberaError`` subclass to its
HTTP status code and RFC 7807-style JSON body.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from jose import JWTError, jwt
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings
from app.core.database import (
    _get_session_factory,
    reset_tenant_context,
    set_tenant_context,
)
from app.core.exceptions import KuberaError
from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.chart_of_accounts import router as coa_router
from app.api.v1.ledger import router as ledger_router
from app.api.v1.hedges import router as hedge_router
from app.api.v1.fx_revaluation import router as fx_router
from app.api.v1.intercompany import router as ic_router
from app.api.v1.accounting_period import router as period_router
from app.api.v1.treasury import router as treasury_router
from app.api.v1.payments_compliance import router as payments_router
from app.core.middleware import SecurityHeadersMiddleware
from app.services.auth_service import AuthService


class TenantIsolationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        auth_header = request.headers.get("authorization")
        token = None
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ")

        request.state.tenant_id = None
        request.state.user_id = None
        ctx_token = set_tenant_context(None)
        if token:
            try:
                payload = jwt.decode(
                    token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
                )
                tenant_id = payload.get("tenant_id")
                user_id = payload.get("sub")
                if payload.get("type") == "access" and tenant_id and user_id:
                    request.state.tenant_id = tenant_id
                    request.state.user_id = user_id
                    ctx_token = set_tenant_context(uuid.UUID(tenant_id))
            except (JWTError, ValueError):
                pass

        try:
            return await call_next(request)
        finally:
            reset_tenant_context(ctx_token)


class IpAllowlistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if (
            path in {"/health"}
            or path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/openapi")
        ):
            return await call_next(request)

        tenant_id = getattr(request.state, "tenant_id", None)
        if tenant_id is None:
            return await call_next(request)

        svc = AuthService()
        session_factory = _get_session_factory()
        async with session_factory() as session:
            client_ip = request.client.host if request.client else "127.0.0.1"
            allowed = await svc.is_ip_allowed(session, uuid.UUID(tenant_id), client_ip)
            if not allowed:
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        return await call_next(request)


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
    app.add_middleware(TenantIsolationMiddleware)
    app.add_middleware(IpAllowlistMiddleware)
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
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(users_router, prefix=API_PREFIX)
    app.include_router(coa_router, prefix=API_PREFIX)
    app.include_router(ledger_router, prefix=API_PREFIX)
    app.include_router(hedge_router, prefix=API_PREFIX)
    app.include_router(fx_router, prefix=API_PREFIX)
    app.include_router(ic_router, prefix=API_PREFIX)
    app.include_router(period_router, prefix=API_PREFIX)
    app.include_router(treasury_router, prefix=API_PREFIX)
    app.include_router(payments_router, prefix=API_PREFIX)

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        return {"status": "ok", "version": app.version}

    return app


app = create_app()
