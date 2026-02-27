"""
NexusTreasury — API Layer Tests
Covers app/api/v1/: accounts, payments, positions, forecasts, instruments, reports
and app/main.py health/exception handlers.

Uses FastAPI TestClient with dependency overrides for DB and auth.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models.entities import BankAccount, Entity
from app.models.transactions import CashPosition


# ─── Test DB & client setup ───────────────────────────────────────────────────

@pytest.fixture(scope="module")
def test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    # Apply SQLite triggers for transaction immutability
    from app.models.transactions import SQLITE_TRIGGERS
    with engine.connect() as conn:
        for stmt in SQLITE_TRIGGERS.strip().split("END;"):
            stmt = stmt.strip()
            if stmt:
                from sqlalchemy import text
                conn.execute(text(stmt + "END;"))
        conn.commit()
    return engine


@pytest.fixture(scope="module")
def TestSession(test_engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def db(TestSession):
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="module")
def client(TestSession):
    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ─── Auth token helpers ───────────────────────────────────────────────────────

def analyst_headers():
    token = create_access_token("user_analyst_1", "treasury_analyst")
    return {"Authorization": f"Bearer {token}"}


def manager_headers():
    token = create_access_token("user_manager_1", "treasury_manager")
    return {"Authorization": f"Bearer {token}"}


def admin_headers():
    token = create_access_token("user_admin_1", "system_admin")
    return {"Authorization": f"Bearer {token}"}


def auditor_headers():
    token = create_access_token("user_auditor_1", "auditor")
    return {"Authorization": f"Bearer {token}"}


# ─── Fixtures: entity + account ───────────────────────────────────────────────

@pytest.fixture
def api_entity(db):
    entity = Entity(name="API Test Corp", entity_type="parent", base_currency="EUR")
    db.add(entity)
    db.flush()
    db.commit()
    return entity


@pytest.fixture
def api_account(db, api_entity):
    account = BankAccount(
        entity_id=api_entity.id,
        iban="DE89370400440532013600",
        bic="COBADEFFXXX",
        currency="EUR",
        overdraft_limit=Decimal("1000.00"),
        account_status="active",
    )
    db.add(account)
    db.commit()
    return account


@pytest.fixture
def funded_api_account(db, api_account):
    pos = CashPosition(
        account_id=api_account.id,
        position_date=date.today(),
        value_date_balance=Decimal("25000.00"),
        entry_date_balance=Decimal("25000.00"),
        currency="EUR",
    )
    db.add(pos)
    db.commit()
    return api_account


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status_field(self, client):
        resp = client.get("/health")
        body = resp.json()
        assert "status" in body
        assert body["status"] in ("healthy", "degraded")

    def test_health_has_version(self, client):
        resp = client.get("/health")
        assert "version" in resp.json()

    def test_health_has_db_connected_field(self, client):
        resp = client.get("/health")
        assert "db_connected" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuth:
    def test_no_token_returns_403(self, client):
        resp = client.get("/api/v1/accounts/")
        assert resp.status_code in (401, 403)

    def test_invalid_token_returns_401(self, client):
        resp = client.get(
            "/api/v1/accounts/",
            headers={"Authorization": "Bearer not_a_real_token"},
        )
        assert resp.status_code == 401

    def test_valid_token_accepted(self, client):
        resp = client.get("/api/v1/accounts/", headers=analyst_headers())
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccountsAPI:
    def test_list_accounts_empty(self, client):
        resp = client.get("/api/v1/accounts/", headers=analyst_headers())
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_accounts_returns_created(self, client, api_account):
        resp = client.get("/api/v1/accounts/", headers=analyst_headers())
        assert resp.status_code == 200
        ids = [a["id"] for a in resp.json()]
        assert api_account.id in ids

    def test_list_accounts_filter_by_entity(self, client, api_account, api_entity):
        resp = client.get(
            f"/api/v1/accounts/?entity_id={api_entity.id}",
            headers=analyst_headers(),
        )
        assert resp.status_code == 200
        for a in resp.json():
            assert a["entity_id"] == api_entity.id

    def test_get_account_by_id(self, client, api_account):
        resp = client.get(f"/api/v1/accounts/{api_account.id}", headers=analyst_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["iban"] == "DE89370400440532013600"
        assert body["currency"] == "EUR"

    def test_get_account_not_found(self, client):
        resp = client.get("/api/v1/accounts/nonexistent-id", headers=analyst_headers())
        assert resp.status_code == 404

    def test_create_account_as_admin(self, client, api_entity):
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "entity_id": api_entity.id,
                "iban": "DE89370400440532013700",
                "bic": "COBADEFFXXX",
                "currency": "EUR",
                "overdraft_limit": "500.00",
            },
            headers=admin_headers(),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["iban"] == "DE89370400440532013700"

    def test_create_account_analyst_forbidden(self, client, api_entity):
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "entity_id": api_entity.id,
                "iban": "DE89370400440532013800",
                "bic": "COBADEFFXXX",
                "currency": "EUR",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 403

    def test_create_account_entity_not_found(self, client):
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "entity_id": "nonexistent-entity",
                "iban": "DE89370400440532013900",
                "bic": "COBADEFFXXX",
                "currency": "EUR",
            },
            headers=admin_headers(),
        )
        assert resp.status_code == 404

    def test_create_account_duplicate_iban(self, client, api_entity, api_account):
        resp = client.post(
            "/api/v1/accounts/",
            json={
                "entity_id": api_entity.id,
                "iban": api_account.iban,  # duplicate
                "bic": "COBADEFFXXX",
                "currency": "EUR",
            },
            headers=admin_headers(),
        )
        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPaymentsAPI:
    def _payment_body(self, account: BankAccount) -> dict:
        return {
            "debtor_account_id": account.id,
            "debtor_iban": account.iban,
            "beneficiary_name": "Legit Supplier Ltd",
            "beneficiary_bic": "NWBKGB2LXXX",
            "beneficiary_iban": "GB29NWBK60161331926819",
            "beneficiary_country": "GB",
            "amount": "500.00",
            "currency": "EUR",
            "execution_date": str(date.today()),
            "remittance_info": "INV-API-001",
        }

    def test_initiate_payment_success(self, client, funded_api_account):
        resp = client.post(
            "/api/v1/payments/",
            json=self._payment_body(funded_api_account),
            headers=analyst_headers(),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "PENDING_APPROVAL"
        assert body["beneficiary_name"] == "Legit Supplier Ltd"

    def test_initiate_payment_auditor_forbidden(self, client, funded_api_account):
        resp = client.post(
            "/api/v1/payments/",
            json=self._payment_body(funded_api_account),
            headers=auditor_headers(),
        )
        assert resp.status_code == 403

    def test_initiate_payment_invalid_amount(self, client, funded_api_account):
        body = self._payment_body(funded_api_account)
        body["amount"] = "not_a_number"
        resp = client.post(
            "/api/v1/payments/",
            json=body,
            headers=analyst_headers(),
        )
        assert resp.status_code == 422

    def test_get_payment_by_id(self, client, funded_api_account):
        # First create one
        create_resp = client.post(
            "/api/v1/payments/",
            json=self._payment_body(funded_api_account),
            headers=analyst_headers(),
        )
        assert create_resp.status_code == 201
        payment_id = create_resp.json()["id"]

        get_resp = client.get(
            f"/api/v1/payments/{payment_id}",
            headers=analyst_headers(),
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == payment_id

    def test_get_payment_not_found(self, client):
        resp = client.get(
            "/api/v1/payments/nonexistent-payment-id",
            headers=analyst_headers(),
        )
        assert resp.status_code == 404

    def test_initiate_payment_returns_end_to_end_id(self, client, funded_api_account):
        resp = client.post(
            "/api/v1/payments/",
            json=self._payment_body(funded_api_account),
            headers=analyst_headers(),
        )
        assert resp.status_code == 201
        assert resp.json()["end_to_end_id"].startswith("E2E-")


# ═══════════════════════════════════════════════════════════════════════════════
# POSITIONS
# ═══════════════════════════════════════════════════════════════════════════════

class TestPositionsAPI:
    def test_get_position_success(self, client, funded_api_account):
        resp = client.get(
            f"/api/v1/positions/{funded_api_account.id}",
            headers=analyst_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["account_id"] == funded_api_account.id
        assert body["currency"] == "EUR"
        assert "balance" in body

    def test_get_position_requires_auth(self, client, funded_api_account):
        resp = client.get(f"/api/v1/positions/{funded_api_account.id}")
        assert resp.status_code in (401, 403)

    def test_get_position_auditor_can_read(self, client, funded_api_account):
        resp = client.get(
            f"/api/v1/positions/{funded_api_account.id}",
            headers=auditor_headers(),
        )
        assert resp.status_code == 200

    def test_get_position_no_cash_row(self, client, api_account):
        # Account exists but no CashPosition row
        resp = client.get(
            f"/api/v1/positions/{api_account.id}",
            headers=analyst_headers(),
        )
        # Either returns 200 with zero balance or 404 — both acceptable
        assert resp.status_code in (200, 404)


# ═══════════════════════════════════════════════════════════════════════════════
# FORECASTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestForecastsAPI:
    def test_create_forecast_success(self, client, api_account):
        resp = client.post(
            "/api/v1/forecasts/",
            json={
                "account_id": api_account.id,
                "currency": "EUR",
                "expected_date": str(date.today() + timedelta(days=7)),
                "forecast_amount": "15000.00",
                "description": "Expected vendor payment",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "created"

    def test_create_forecast_invalid_amount(self, client, api_account):
        resp = client.post(
            "/api/v1/forecasts/",
            json={
                "account_id": api_account.id,
                "currency": "EUR",
                "expected_date": str(date.today() + timedelta(days=5)),
                "forecast_amount": "not_a_decimal",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 422

    def test_create_forecast_auditor_forbidden(self, client, api_account):
        resp = client.post(
            "/api/v1/forecasts/",
            json={
                "account_id": api_account.id,
                "currency": "EUR",
                "expected_date": str(date.today() + timedelta(days=3)),
                "forecast_amount": "5000.00",
            },
            headers=auditor_headers(),
        )
        assert resp.status_code == 403

    def test_get_variance_report(self, client):
        from_d = str(date.today() - timedelta(days=30))
        to_d = str(date.today())
        resp = client.get(
            f"/api/v1/forecasts/variance-report?from_date={from_d}&to_date={to_d}",
            headers=analyst_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total_forecast" in body
        assert "total_actual" in body
        assert "net_variance" in body

    def test_variance_report_with_entity_filter(self, client, api_entity):
        from_d = str(date.today() - timedelta(days=30))
        to_d = str(date.today())
        resp = client.get(
            f"/api/v1/forecasts/variance-report?from_date={from_d}&to_date={to_d}&entity_id={api_entity.id}",
            headers=analyst_headers(),
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# INSTRUMENTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestInstrumentsAPI:
    def test_calculate_interest_act360(self, client):
        resp = client.post(
            "/api/v1/instruments/calculate-interest",
            json={
                "currency": "EUR",
                "principal": "1000000.00",
                "annual_rate": "0.04",
                "start_date": "2024-01-01",
                "maturity_date": "2025-01-01",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert Decimal(body["interest_amount"]) > Decimal("0")
        assert body["accrual_period_days"] == 366
        assert not body["is_negative_rate"]

    def test_calculate_interest_negative_rate(self, client):
        resp = client.post(
            "/api/v1/instruments/calculate-interest",
            json={
                "currency": "EUR",
                "principal": "500000.00",
                "annual_rate": "-0.005",
                "start_date": "2024-01-01",
                "maturity_date": "2024-07-01",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert Decimal(body["interest_amount"]) < Decimal("0")
        assert body["is_negative_rate"] is True

    def test_calculate_interest_invalid_principal(self, client):
        resp = client.post(
            "/api/v1/instruments/calculate-interest",
            json={
                "currency": "EUR",
                "principal": "not_a_number",
                "annual_rate": "0.04",
                "start_date": "2024-01-01",
                "maturity_date": "2025-01-01",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 422

    def test_calculate_interest_with_convention_override(self, client):
        resp = client.post(
            "/api/v1/instruments/calculate-interest",
            json={
                "currency": "EUR",
                "principal": "1000000.00",
                "annual_rate": "0.03",
                "start_date": "2024-01-01",
                "maturity_date": "2024-07-01",
                "convention_override": "ACT/365",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["convention_used"] == "ACT/365"

    def test_calculate_interest_requires_auth(self, client):
        resp = client.post(
            "/api/v1/instruments/calculate-interest",
            json={
                "currency": "EUR",
                "principal": "1000000.00",
                "annual_rate": "0.04",
                "start_date": "2024-01-01",
                "maturity_date": "2025-01-01",
            },
        )
        assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestReportsAPI:
    def test_var_calculation(self, client):
        resp = client.post(
            "/api/v1/reports/var",
            json={
                "pair": "EUR/USD",
                "position_value": "1000000.00",
                "confidence": "0.99",
            },
            headers=analyst_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pair"] == "EUR/USD"
        assert Decimal(body["var_amount"]) >= Decimal("0")
        assert Decimal(body["confidence_level"]) == Decimal("0.99")

    def test_var_default_confidence(self, client):
        resp = client.post(
            "/api/v1/reports/var",
            json={"pair": "GBP/USD", "position_value": "500000.00"},
            headers=analyst_headers(),
        )
        assert resp.status_code == 200

    def test_var_invalid_position_value(self, client):
        resp = client.post(
            "/api/v1/reports/var",
            json={"pair": "EUR/USD", "position_value": "not_a_number"},
            headers=analyst_headers(),
        )
        assert resp.status_code == 422

    def test_gl_post_event(self, client):
        resp = client.post(
            "/api/v1/reports/gl/post",
            json={
                "event_id": "EVT-API-001",
                "event_type": "PAYMENT_SENT",
                "amount": "10000.00",
                "currency": "EUR",
                "metadata": {},
            },
            headers=manager_hea