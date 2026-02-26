"""
NexusTreasury — Phase 3 Test Suite: Payment Factory
FIX: session.flush() for entity.id; remove available_balance from CashPosition.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import (
    InsufficientFundsError,
    InvalidBICError,
    InvalidIBANError,
    SanctionsHitError,
    SelfApprovalError,
)
from app.models.entities import BankAccount, Entity
from app.models.payments import Payment, SanctionsAlert
from app.models.transactions import CashPosition
from app.services.payment_factory import PaymentService


@pytest.fixture
def entity_and_accounts(db_session):
    entity = Entity(name="Payment Corp", entity_type="parent", base_currency="EUR")
    db_session.add(entity)
    db_session.flush()  # <-- populate entity.id before BankAccount uses it
    payer = BankAccount(
        entity_id=entity.id,
        iban="DE89370400440532013200",
        bic="COBADEFFXXX",
        currency="EUR",
        overdraft_limit=Decimal("5000.00"),
    )
    db_session.add(payer)
    db_session.commit()
    return entity, payer


@pytest.fixture
def funded_account(db_session, entity_and_accounts):
    _, payer = entity_and_accounts
    pos = CashPosition(
        account_id=payer.id,
        position_date=date.today(),
        value_date_balance=Decimal("50000.00"),
        entry_date_balance=Decimal("50000.00"),  # FIX: no available_balance column
        currency="EUR",
    )
    db_session.add(pos)
    db_session.commit()
    return payer


@pytest.fixture
def payment_service(db_session):
    return PaymentService(db_session)


# ─── Four-Eyes Tests ──────────────────────────────────────────────────────────


def test_self_approval_blocked(db_session, funded_account, payment_service):
    payment = payment_service.initiate_payment(
        payer_iban=funded_account.iban,
        payee_iban="GB29NWBK60161331926819",
        payee_name="Legit Supplier Ltd",
        payee_bic="NWBKGB2LXXX",
        amount=Decimal("1000.00"),
        currency="EUR",
        reference="INV-2024-001",
        initiated_by="analyst_1",
    )
    with pytest.raises(SelfApprovalError):
        payment_service.approve_payment(payment_id=payment.id, approved_by="analyst_1")


def test_valid_four_eyes_approval(db_session, funded_account, payment_service):
    payment = payment_service.initiate_payment(
        payer_iban=funded_account.iban,
        payee_iban="GB29NWBK60161331926819",
        payee_name="Legit Supplier Ltd",
        payee_bic="NWBKGB2LXXX",
        amount=Decimal("500.00"),
        currency="EUR",
        reference="INV-2024-002",
        initiated_by="analyst_1",
    )
    approved = payment_service.approve_payment(
        payment_id=payment.id, approved_by="manager_1"
    )
    assert approved.status == "APPROVED"
    assert approved.approved_by == "manager_1"


def test_double_approval_blocked(db_session, funded_account, payment_service):
    payment = payment_service.initiate_payment(
        payer_iban=funded_account.iban,
        payee_iban="GB29NWBK60161331926819",
        payee_name="Legit Supplier Ltd",
        payee_bic="NWBKGB2LXXX",
        amount=Decimal("500.00"),
        currency="EUR",
        reference="INV-2024-003",
        initiated_by="analyst_1",
    )
    payment_service.approve_payment(payment_id=payment.id, approved_by="manager_1")
    with pytest.raises(Exception):
        payment_service.approve_payment(payment_id=payment.id, approved_by="admin_1")


# ─── Sanctions Screening Tests ────────────────────────────────────────────────


def test_exact_sanctions_hit_blocked(db_session, funded_account, payment_service):
    with pytest.raises(SanctionsHitError) as exc_info:
        payment_service.initiate_payment(
            payer_iban=funded_account.iban,
            payee_iban="IR000000000000000000",
            payee_name="ISLAMIC REVOLUTIONARY GUARD CORPS",
            payee_bic="IRXXXXX",
            amount=Decimal("50000.00"),
            currency="EUR",
            reference="SANCTION-TEST-001",
            initiated_by="analyst_1",
        )
    assert exc_info.value.match_score >= 0.85


def test_fuzzy_sanctions_hit_blocked(db_session, funded_account, payment_service):
    with pytest.raises(SanctionsHitError):
        payment_service.initiate_payment(
            payer_iban=funded_account.iban,
            payee_iban="RU000000000000000001",
            payee_name="Sberbnk PJSC",
            payee_bic="SABRRUММXXX",
            amount=Decimal("10000.00"),
            currency="EUR",
            reference="SANCTION-TEST-002",
            initiated_by="analyst_1",
        )


def test_clean_payment_passes_sanctions(db_session, funded_account, payment_service):
    payment = payment_service.initiate_payment(
        payer_iban=funded_account.iban,
        payee_iban="GB29NWBK60161331926819",
        payee_name="Acme Consulting Ltd",
        payee_bic="NWBKGB2LXXX",
        amount=Decimal("2500.00"),
        currency="EUR",
        reference="INV-CLEAN-001",
        initiated_by="analyst_1",
    )
    assert payment.status == "PENDING_APPROVAL"
    alerts = db_session.query(SanctionsAlert).filter_by(payment_id=payment.id).all()
    assert len(alerts) == 0


# ─── IBAN / BIC Validation Tests ──────────────────────────────────────────────


def test_invalid_iban_rejected(db_session, funded_account, payment_service):
    with pytest.raises(InvalidIBANError):
        payment_service.initiate_payment(
            payer_iban=funded_account.iban,
            payee_iban="DE00INVALID000000",
            payee_name="Legit Corp",
            payee_bic="COBADEFFXXX",
            amount=Decimal("100.00"),
            currency="EUR",
            reference="IBAN-TEST-001",
            initiated_by="analyst_1",
        )


def test_invalid_bic_rejected(db_session, funded_account, payment_service):
    with pytest.raises(InvalidBICError):
        payment_service.initiate_payment(
            payer_iban=funded_account.iban,
            payee_iban="GB29NWBK60161331926819",
            payee_name="Legit Corp",
            payee_bic="NOTABIC",
            amount=Decimal("100.00"),
            currency="EUR",
            reference="BIC-TEST-001",
            initiated_by="analyst_1",
        )


# ─── Insufficient Funds Tests ─────────────────────────────────────────────────


def test_insufficient_funds_raises_error(
    db_session, entity_and_accounts, payment_service
):
    _, payer = entity_and_accounts
    pos = CashPosition(
        account_id=payer.id,
        position_date=date.today(),
        value_date_balance=Decimal("100.00"),
        entry_date_balance=Decimal("100.00"),  # FIX: no available_balance
        currency="EUR",
    )
    db_session.add(pos)
    db_session.commit()

    with pytest.raises(InsufficientFundsError):
        payment_service.initiate_payment(
            payer_iban=payer.iban,
            payee_iban="GB29NWBK60161331926819",
            payee_name="Supplier Ltd",
            payee_bic="NWBKGB2LXXX",
            amount=Decimal("10000.00"),
            currency="EUR",
            reference="FUNDS-TEST-001",
            initiated_by="analyst_1",
        )


# ─── PAIN.001 Export Tests ────────────────────────────────────────────────────


def test_pain001_export_valid_xml(db_session, funded_account, payment_service):
    from lxml import etree

    payment = payment_service.initiate_payment(
        payer_iban=funded_account.iban,
        payee_iban="GB29NWBK60161331926819",
        payee_name="Export Test Ltd",
        payee_bic="NWBKGB2LXXX",
        amount=Decimal("750.00"),
        currency="EUR",
        reference="PAIN-TEST-001",
        initiated_by="analyst_1",
    )
    payment_service.approve_payment(payment_id=payment.id, approved_by="manager_1")
    xml_bytes = payment_service.export_pain001(payment_id=payment.id)
    root = etree.fromstring(xml_bytes)
    assert root is not None
    assert "pain.001" in root.nsmap.get(None, "") or any(
        "pain.001" in v for v in root.nsmap.values()
    )


def test_pain001_contains_correct_amount(db_session, funded_account, payment_service):
    payment = payment_service.initiate_payment(
        payer_iban=funded_account.iban,
        payee_iban="GB29NWBK60161331926819",
        payee_name="Amount Test Ltd",
        payee_bic="NWBKGB2LXXX",
        amount=Decimal("1234.56"),
        currency="EUR",
        reference="PAIN-AMOUNT-001",
        initiated_by="analyst_1",
    )
    payment_service.approve_payment(payment_id=payment.id, approved_by="manager_1")
    xml_str = payment_service.export_pain001(payment_id=payment.id).decode("utf-8")
    assert "1234.56" in xml_str
    assert "EUR" in xml_str
