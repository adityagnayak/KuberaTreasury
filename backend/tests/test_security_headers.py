"""Tests for SecurityHeadersMiddleware.

Verifies that the correct HTTP security headers are attached to every
response by the middleware registered in ``app.main``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport

from app.main import app


# ─────────────────────────────────── Fixtures ─────────────────────────────────


@pytest_asyncio.fixture
async def client():  # type: ignore[misc]
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ─────────────────────────────────── Tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_security_headers_on_health(client: httpx.AsyncClient) -> None:
    """All six OWASP security headers must be present on every response."""
    response = await client.get("/health")

    assert response.status_code == 200

    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains; preload"
    )
    assert response.headers["content-security-policy"] == (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == (
        "geolocation=(), microphone=(), camera=(), payment=(), usb=()"
    )


@pytest.mark.asyncio
async def test_cache_control_on_api_routes(client: httpx.AsyncClient) -> None:
    """Cache-Control: no-store must be set on /api/* routes only."""
    # An /api/ path (404 is fine — the header is applied before routing)
    api_response = await client.get("/api/v1/does-not-exist")
    assert api_response.headers.get("cache-control") == "no-store"

    # /health is NOT under /api/ — Cache-Control must be absent
    health_response = await client.get("/health")
    assert "cache-control" not in health_response.headers
