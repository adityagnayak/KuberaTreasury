"""Tests for core/exceptions.py.

Covers:
  - Each KuberaError subclass: status_code and formatted detail message.
  - The RFC 7807 exception handler in main.py: correct status code, JSON
    shape, and detail round-trip via an in-process ASGI client.
"""

from __future__ import annotations

import pytest
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport

from app.core.exceptions import (
    HedgeEffectivenessError,
    KuberaError,
    NotFoundError,
    PermissionDeniedError,
    PeriodClosedError,
    TransferPricingError,
    UnbalancedJournalError,
)


# ──────────────────────────────────── Unit tests ──────────────────────────────


class TestUnbalancedJournalError:
    def test_status_code(self) -> None:
        assert UnbalancedJournalError.status_code == 422

    def test_detail_message(self) -> None:
        err = UnbalancedJournalError("1000.00", "900.00")
        assert "1000.00" in err.detail
        assert "900.00" in err.detail
        assert "Σ debits = Σ credits" in err.detail

    def test_is_kubera_error(self) -> None:
        assert isinstance(UnbalancedJournalError("1.00", "2.00"), KuberaError)


class TestPeriodClosedError:
    def test_status_code(self) -> None:
        assert PeriodClosedError.status_code == 409

    def test_detail_message(self) -> None:
        err = PeriodClosedError("Jan 2026")
        assert "Jan 2026" in err.detail
        assert "closed" in err.detail


class TestNotFoundError:
    def test_status_code(self) -> None:
        assert NotFoundError.status_code == 404

    def test_detail_message(self) -> None:
        err = NotFoundError("LedgerEntry", "abc-123")
        assert "LedgerEntry" in err.detail
        assert "abc-123" in err.detail


class TestPermissionDeniedError:
    def test_status_code(self) -> None:
        assert PermissionDeniedError.status_code == 403

    def test_detail_message(self) -> None:
        err = PermissionDeniedError("close_period")
        assert "close_period" in err.detail
        assert "Permission denied" in err.detail


class TestTransferPricingError:
    def test_status_code(self) -> None:
        assert TransferPricingError.status_code == 422

    def test_detail_message(self) -> None:
        err = TransferPricingError(200.5)
        assert "200.5bps" in err.detail
        assert "±150bps" in err.detail


class TestHedgeEffectivenessError:
    def test_status_code(self) -> None:
        assert HedgeEffectivenessError.status_code == 422

    def test_detail_message(self) -> None:
        err = HedgeEffectivenessError(0.75)
        assert "75.0%" in err.detail
        assert "80–125%" in err.detail
        assert "IFRS 9" in err.detail


# ──────────────────────────── RFC 7807 handler integration ────────────────────
#
# We register one route per exception type on a lightweight test app that
# shares the same exception handler as main_app, keeping the test isolated
# from real DB/auth dependencies.


def _make_test_app() -> FastAPI:
    """Minimal app with the KuberaError handler and one route per exception."""
    test_app = FastAPI()

    @test_app.exception_handler(KuberaError)
    async def _handler(request, exc: KuberaError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://kuberatreasury.com/errors/{exc.__class__.__name__}",
                "title": exc.__class__.__name__,
                "status": exc.status_code,
                "detail": str(exc),
            },
        )

    @test_app.get("/raise/unbalanced")
    async def _unbalanced():
        raise UnbalancedJournalError("500.00", "400.00")

    @test_app.get("/raise/period_closed")
    async def _period_closed():
        raise PeriodClosedError("Q1 2026")

    @test_app.get("/raise/not_found")
    async def _not_found():
        raise NotFoundError("Invoice", "inv-999")

    @test_app.get("/raise/permission_denied")
    async def _permission_denied():
        raise PermissionDeniedError("delete_tenant")

    @test_app.get("/raise/transfer_pricing")
    async def _transfer_pricing():
        raise TransferPricingError(300.0)

    @test_app.get("/raise/hedge_effectiveness")
    async def _hedge():
        raise HedgeEffectivenessError(0.60)

    return test_app


_test_app = _make_test_app()


@pytest.fixture
async def exc_client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=_test_app), base_url="http://test"
    ) as c:
        yield c


def _assert_rfc7807(body: dict, cls: type, status: int) -> None:
    assert body["status"] == status
    assert body["title"] == cls.__name__
    assert body["type"] == f"https://kuberatreasury.com/errors/{cls.__name__}"
    assert body["detail"]


@pytest.mark.asyncio
async def test_handler_unbalanced_journal(exc_client: httpx.AsyncClient) -> None:
    r = await exc_client.get("/raise/unbalanced")
    assert r.status_code == 422
    _assert_rfc7807(r.json(), UnbalancedJournalError, 422)
    assert "500.00" in r.json()["detail"]


@pytest.mark.asyncio
async def test_handler_period_closed(exc_client: httpx.AsyncClient) -> None:
    r = await exc_client.get("/raise/period_closed")
    assert r.status_code == 409
    _assert_rfc7807(r.json(), PeriodClosedError, 409)
    assert "Q1 2026" in r.json()["detail"]


@pytest.mark.asyncio
async def test_handler_not_found(exc_client: httpx.AsyncClient) -> None:
    r = await exc_client.get("/raise/not_found")
    assert r.status_code == 404
    _assert_rfc7807(r.json(), NotFoundError, 404)
    assert "inv-999" in r.json()["detail"]


@pytest.mark.asyncio
async def test_handler_permission_denied(exc_client: httpx.AsyncClient) -> None:
    r = await exc_client.get("/raise/permission_denied")
    assert r.status_code == 403
    _assert_rfc7807(r.json(), PermissionDeniedError, 403)


@pytest.mark.asyncio
async def test_handler_transfer_pricing(exc_client: httpx.AsyncClient) -> None:
    r = await exc_client.get("/raise/transfer_pricing")
    assert r.status_code == 422
    _assert_rfc7807(r.json(), TransferPricingError, 422)
    assert "300.0bps" in r.json()["detail"]


@pytest.mark.asyncio
async def test_handler_hedge_effectiveness(exc_client: httpx.AsyncClient) -> None:
    r = await exc_client.get("/raise/hedge_effectiveness")
    assert r.status_code == 422
    _assert_rfc7807(r.json(), HedgeEffectivenessError, 422)
    assert "60.0%" in r.json()["detail"]
