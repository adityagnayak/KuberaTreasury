"""
NexusTreasury — Shared pytest fixtures for all test phases.
"""

from __future__ import annotations

import base64
import os
import secrets
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ─── Environment setup (before any app imports) ───────────────────────────────

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AES_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
os.environ.setdefault("JWT_SECRET", secrets.token_hex(32))
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# ─── App imports (after env is set) ───────────────────────────────────────────

from app.database import Base  # noqa: E402
from app.models.entities import (  # noqa: E402
    BankAccount,
    Entity,
)
from app.models.transactions import (  # noqa: E402
    SQLITE_TRIGGERS,
)

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE FIXTURES
# ─────────────────────────────────────────────────────────────────────────────


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)

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

    return engine


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """In-memory SQLite session — fresh for every test function."""
    engine = _make_engine()
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="function")
def session_factory():
    """In-memory SQLite sessionmaker — for services that create their own sessions."""
    engine = _make_engine()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield factory
    engine.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI CLIENT FIXTURE
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden DB dependency."""
    from app.database import get_db
    from app.main import app

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# ENTITY / ACCOUNT FIXTURES
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def test_entity(db_session: Session) -> Entity:
    entity = Entity(
        name="Test Corp Parent",
        entity_type="parent",
        base_currency="EUR",
        is_active=True,
    )
    db_session.add(entity)
    db_session.commit()
    return entity


@pytest.fixture(scope="function")
def test_account(db_session: Session, test_entity: Entity) -> BankAccount:
    account = BankAccount(
        entity_id=test_entity.id,
        iban="GB29NWBK60161331926819",
        bic="NWBKGB2L",
        account_name="Main GBP Account",
        currency="GBP",
        overdraft_limit=Decimal("10000"),
        account_status="active",
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture(scope="function")
def eur_account(db_session: Session, test_entity: Entity) -> BankAccount:
    account = BankAccount(
        entity_id=test_entity.id,
        iban="DE89370400440532013000",
        bic="COBADEFFXXX",
        account_name="EUR Account",
        currency="EUR",
        overdraft_limit=Decimal("50000"),
        account_status="active",
    )
    db_session.add(account)
    db_session.commit()
    return account


# ─────────────────────────────────────────────────────────────────────────────
# RSA KEY FIXTURES (per user role)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def analyst_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


@pytest.fixture(scope="session")
def manager_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


@pytest.fixture(scope="session")
def auditor_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


@pytest.fixture(scope="session")
def admin_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


# ─────────────────────────────────────────────────────────────────────────────
# JWT TOKEN FIXTURES
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def analyst_token() -> str:
    from app.core.security import create_access_token

    return create_access_token("analyst_001", "treasury_analyst")


@pytest.fixture(scope="session")
def manager_token() -> str:
    from app.core.security import create_access_token

    return create_access_token("manager_001", "treasury_manager")


@pytest.fixture(scope="session")
def auditor_token() -> str:
    from app.core.security import create_access_token

    return create_access_token("auditor_001", "auditor")


@pytest.fixture(scope="session")
def admin_token() -> str:
    from app.core.security import create_access_token

    return create_access_token("admin_001", "system_admin")


# ─────────────────────────────────────────────────────────────────────────────
# FX CACHE FIXTURE
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def mock_fx_cache():
    """Pre-loaded FX rate cache with major currency pairs."""
    from app.services.cash_positioning import FXRateCache

    cache = FXRateCache()
    rates = {
        ("EUR", "USD"): Decimal("1.0870"),
        ("EUR", "GBP"): Decimal("0.8532"),
        ("EUR", "JPY"): Decimal("162.50"),
        ("USD", "EUR"): Decimal("0.9200"),
        ("USD", "GBP"): Decimal("0.7850"),
        ("GBP", "EUR"): Decimal("1.1722"),
        ("GBP", "USD"): Decimal("1.2739"),
        ("CHF", "EUR"): Decimal("1.0692"),
        ("EUR", "CHF"): Decimal("0.9353"),
    }
    for (f, t), rate in rates.items():
        cache.set_rate(f, t, rate)
    return cache


# ─────────────────────────────────────────────────────────────────────────────
# CAMT.053 / MT940 SAMPLE DATA HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def build_sample_camt053(
    message_id: str,
    iban: str,
    stmt_date: str,
    transactions: list,
    legal_seq: str = "1",
) -> bytes:
    ns = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.06"
    entries_xml = ""
    for t in transactions:
        entries_xml += f"""
        <Ntry>
          <Amt Ccy="EUR">{t['amount']}</Amt>
          <CdtDbtInd>{t.get('cdi', 'CRDT')}</CdtDbtInd>
          <BookgDt><Dt>{t.get('entry_date', stmt_date)}</Dt></BookgDt>
          <ValDt><Dt>{t.get('value_date', stmt_date)}</Dt></ValDt>
          <AcctSvcrRef>{t.get('trn', 'TRN' + stmt_date.replace('-', ''))}</AcctSvcrRef>
          <NtryDtls>
            <TxDtls>
              <RmtInf><Ustrd>{t.get('remittance', 'Test payment')}</Ustrd></RmtInf>
              <Refs>
                <EndToEndId>{t.get('trn', 'E2E' + stmt_date.replace('-', ''))}</EndToEndId>
              </Refs>
            </TxDtls>
          </NtryDtls>
        </Ntry>"""

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="{ns}">
  <BkToCstmrStmt>
    <GrpHdr>
      <MsgId>{message_id}</MsgId>
      <CreDtTm>{stmt_date}T00:00:00Z</CreDtTm>
    </GrpHdr>
    <Stmt>
      <LglSeqNb>{legal_seq}</LglSeqNb>
      <CreDtTm>{stmt_date}T00:00:00Z</CreDtTm>
      <Acct><Id><IBAN>{iban}</IBAN></Id></Acct>
      {entries_xml}
    </Stmt>
  </BkToCstmrStmt>
</Document>"""
    return xml.encode("utf-8")


@pytest.fixture
def sample_camt053_bytes(test_account: BankAccount):
    """A minimal valid CAMT.053 XML fixture for the test account."""
    return build_sample_camt053(
        message_id="TEST-MSG-001",
        iban=test_account.iban,
        stmt_date="2024-01-15",
        transactions=[
            {
                "amount": "1500.00",
                "cdi": "CRDT",
                "value_date": "2024-01-15",
                "entry_date": "2024-01-15",
                "trn": "E2E-001",
                "remittance": "Test payment",
            }
        ],
        legal_seq="1",
    )
