"""KuberaTreasury — reusable middleware components.

Centralises all Starlette BaseHTTPMiddleware subclasses so they can be
imported in ``app.main`` and tested in isolation.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ─────────────────────────────────────────────── Security-headers middleware ──


_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)

_PERMISSIONS = "geolocation=(), microphone=(), camera=(), payment=(), usb=()"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach OWASP-recommended security headers to every response.

    In addition, ``Cache-Control: no-store`` is added to all responses for
    paths under ``/api/`` to prevent sensitive data being cached by proxies
    or browsers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)

        # Applied unconditionally to all routes ─────────────────────────────
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = _PERMISSIONS

        # Applied only on /api/* routes ──────────────────────────────────────
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"

        return response
