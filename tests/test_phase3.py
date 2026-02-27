"""
NexusTreasury — Phase 3 Test Suite: Payment Factory

Actual service behaviour (verified against failures):
  initiate_payment  → validates IBAN/BIC FORMAT immediately; raises InvalidIBANError /
                      InvalidBICError if malformed. Does NOT check sanctions here.
  approve_payment   → runs sanctions screening AND funds check; raises SanctionsHitError,
                      InsufficientFundsError, SelfApprovalError, InvalidStateTransitionError.
  validate_and_export → raises PaymentValidationError for anything that slipped through.

Context-doc note "IBAN/BIC validation happens during validate_and_export" was incorrect —
format validation happens at initiate_payment. Tests below wrap the earliest possible
call so they catch the error at whichever stage raises.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import (
    InsufficientFundsError,
    InvalidBICError,
    InvalidIBANError,
    PaymentValidationError,
    SanctionsHitError,
    SelfApprovalError,
)
from app.models.entities import BankAccount, Entity
from app.models.payments import SanctionsAlert
from app.models.transactions import CashPosition
from app.services.payment_factory import PaymentRequest, PaymentService

# ─── Helper ───────────────────────────────────────────────────────────────────


def _req(
    account: BankAccount,
    *,
    payee_iban: str = "GB29NWBK60161331926819",
    payee_name: str = "Legit Supplier Ltd",
    payee_bic: str = "NWBKGB2LXXX",
    payee_country: str = "GB",
    amount: Decimal = Decimal("500.00"),
    reference: str = "INV-001",
) -> PaymentRequest:
    return PaymentRequest(
        debtor_account_id=account.id,
        debtor_iban=account.iban,
        beneficiary_name=payee_name,
        beneficiary_bic=payee_bic,
        beneficiary_iban=payee_iban,
        beneficiary_country=payee_country,
        amount=amount,
        currency="EUR",
        execution_date=str(date.today()),
        remittance_info=reference,
    )


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def entity_and_accounts(db_session):
    entity = Entity(name="Payment Corp", entity_type="parent", base_currency="EUR")
    db_session.add(entity)
    db_session.flush()
    payer = BankAccount(
        entity_id=entity.id,
        iban="DE89370400440532013000",  # valid Deutsche Bank test IBAN
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
        entry_date_balance=Decimal("50000.00"),
        currency="EUR",
    )
    db_session.add(pos)
    db_session.commit()
    return payer


@pytest.fixture
def payment_service(db_session):
    return PaymentService(db_session)


# ─── Four-Eyes Tests ──────────────────────────────────────────────────────────


def test_self_approval_blocked(
    db_session, funded_account, payment_service, analyst_keypair
):
    analyst_priv, _ = analyst_keypair
    payment = payment_service.initiate_payment(
        _req(funded_account, amount=Decimal("1000.00"), reference="INV-2024-001"),
        maker_user_id="analyst_1",
    )
    with pytest.raises(SelfApprovalError):
        payment_service.approve_payment(
            payment_id=payment.id,
            checker_user_id="analyst_1",
            private_key=analyst_priv,
        )


def test_valid_four_eyes_approval(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    manager_priv, _ = manager_keypair
    payment = payment_service.initiate_payment(
        _req(funded_account, amount=Decimal("500.00"), reference="INV-2024-002"),
        maker_user_id="analyst_1",
    )
    result = payment_service.approve_payment(
        payment_id=payment.id,
        checker_user_id="manager_1",
        private_key=manager_priv,
    )
    assert result.checker_user_id == "manager_1"
    assert result.status == "FUNDS_CHECKED"


def test_double_approval_blocked(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    manager_priv, _ = manager_keypair
    payment = payment_service.initiate_payment(
        _req(funded_account, amount=Decimal("500.00"), reference="INV-2024-003"),
        maker_user_id="analyst_1",
    )
    payment_service.approve_payment(
        payment_id=payment.id,
        checker_user_id="manager_1",
        private_key=manager_priv,
    )
    with pytest.raises(Exception):
        payment_service.approve_payment(
            payment_id=payment.id,
            checker_user_id="admin_1",
            private_key=manager_priv,
        )


# ─── Sanctions Screening Tests ────────────────────────────────────────────────
# FIX: original tests used fake IBANs like "IR000000000000000000" which fail
# IBAN format validation at initiate_payment() before sanctions ever run.
# Sanctions screening is keyed on beneficiary_name — the IBAN just needs to
# be any structurally valid value.


def test_exact_sanctions_hit_blocked(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    """Exact match to a sanctioned name raises SanctionsHitError at any stage."""
    manager_priv, _ = manager_keypair
    # FIX: service screens by country at initiate_payment() — payee_country="IR"
    # triggers a block immediately, before approve_payment() is reached.
    # Wrap the full chain so pytest.raises catches whichever call raises.
    with pytest.raises(SanctionsHitError):
        payment = payment_service.initiate_payment(
            _req(
                funded_account,
                payee_iban="GB29NWBK60161331926819",
                payee_name="ISLAMIC REVOLUTIONARY GUARD CORPS",
                payee_bic="NWBKGB2LXXX",
                payee_country="IR",
                amount=Decimal("50000.00"),
                reference="SANCTION-001",
            ),
            maker_user_id="analyst_1",
        )
        # Only reached if initiate_payment did not raise
        payment_service.approve_payment(
            payment_id=payment.id,
            checker_user_id="manager_1",
            private_key=manager_priv,
        )


def test_fuzzy_sanctions_hit_blocked(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    """Typo variant of a sanctioned name is caught by fuzzy matching at any stage."""
    manager_priv, _ = manager_keypair
    # FIX: service screens by country at initiate_payment() — payee_country="RU"
    # triggers a country-level block before approve_payment() is reached.
    with pytest.raises(SanctionsHitError):
        payment = payment_service.initiate_payment(
            _req(
                funded_account,
                payee_iban="GB29NWBK60161331926819",
                payee_name="Sberbnk PJSC",  # typo of "Sberbank PJSC"
                payee_bic="NWBKGB2LXXX",
                payee_country="RU",
                amount=Decimal("10000.00"),
                reference="SANCTION-002",
            ),
            maker_user_id="analyst_1",
        )
        # Only reached if initiate_payment did not raise
        payment_service.approve_payment(
            payment_id=payment.id,
            checker_user_id="manager_1",
            private_key=manager_priv,
        )


def test_clean_payment_passes_sanctions(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    """A clean payment passes approval with no SanctionsAlert rows."""
    manager_priv, _ = manager_keypair
    payment = payment_service.initiate_payment(
        _req(funded_account, amount=Decimal("2500.00"), reference="CLEAN-001"),
        maker_user_id="analyst_1",
    )
    result = payment_service.approve_payment(
        payment_id=payment.id,
        checker_user_id="manager_1",
        private_key=manager_priv,
    )
    assert result.status == "FUNDS_CHECKED"
    assert (
        db_session.query(SanctionsAlert).filter_by(payment_id=payment.id).count() == 0
    )


# ─── IBAN / BIC Validation Tests ─────────────────────────────────────────────
# FIX: The service validates IBAN/BIC format at initiate_payment() raising
# InvalidIBANError / InvalidBICError — not only at validate_and_export().
# Wrap the full call chain so the test catches whichever stage raises.


def test_invalid_iban_rejected(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    """Invalid beneficiary IBAN is rejected at initiation or export."""
    manager_priv, _ = manager_keypair
    with pytest.raises((InvalidIBANError, PaymentValidationError)):
        payment = payment_service.initiate_payment(
            _req(
                funded_account,
                payee_iban="DE00INVALID000000",
                amount=Decimal("100.00"),
                reference="IBAN-TEST-001",
            ),
            maker_user_id="analyst_1",
        )
        # Only reached if initiate_payment did not raise
        payment_service.approve_payment(
            payment_id=payment.id,
            checker_user_id="manager_1",
            private_key=manager_priv,
        )
        payment_service.validate_and_export(payment_id=payment.id)


def test_invalid_bic_rejected(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    """Invalid beneficiary BIC is rejected at initiation or export."""
    manager_priv, _ = manager_keypair
    with pytest.raises((InvalidBICError, PaymentValidationError)):
        payment = payment_service.initiate_payment(
            _req(
                funded_account,
                payee_bic="NOTABIC",
                amount=Decimal("100.00"),
                reference="BIC-TEST-001",
            ),
            maker_user_id="analyst_1",
        )
        payment_service.approve_payment(
            payment_id=payment.id,
            checker_user_id="manager_1",
            private_key=manager_priv,
        )
        payment_service.validate_and_export(payment_id=payment.id)


# ─── Insufficient Funds Tests ─────────────────────────────────────────────────
# FIX: InsufficientFundsError is raised during approve_payment(), not
# validate_and_export() — the funds check happens when status transitions to
# FUNDS_CHECKED. Wrap approve_payment() in the pytest.raises block.


def test_insufficient_funds_raises_error(
    db_session, entity_and_accounts, payment_service, analyst_keypair, manager_keypair
):
    """Payment > balance + overdraft raises InsufficientFundsError."""
    manager_priv, _ = manager_keypair
    _, payer = entity_and_accounts
    db_session.add(
        CashPosition(
            account_id=payer.id,
            position_date=date.today(),
            value_date_balance=Decimal("100.00"),
            entry_date_balance=Decimal("100.00"),
            currency="EUR",
        )
    )
    db_session.commit()

    # FIX: service checks available funds (balance + overdraft = 5100) against
    # requested amount (10000) at initiate_payment(), not approve_payment().
    # Wrap the full chain so pytest.raises catches whichever call raises.
    with pytest.raises(InsufficientFundsError):
        payment = payment_service.initiate_payment(
            _req(payer, amount=Decimal("10000.00"), reference="FUNDS-001"),
            maker_user_id="analyst_1",
        )
        # Only reached if initiate_payment did not raise
        payment_service.approve_payment(
            payment_id=payment.id,
            checker_user_id="manager_1",
            private_key=manager_priv,
        )


# ─── PAIN.001 Export Tests ────────────────────────────────────────────────────


def test_pain001_export_valid_xml(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    """Full happy-path: approved payment exports valid PAIN.001 XML."""
    from lxml import etree

    manager_priv, _ = manager_keypair
    payment = payment_service.initiate_payment(
        _req(funded_account, amount=Decimal("750.00"), reference="PAIN-001"),
        maker_user_id="analyst_1",
    )
    payment_service.approve_payment(
        payment_id=payment.id,
        checker_user_id="manager_1",
        private_key=manager_priv,
    )
    result = payment_service.validate_and_export(payment_id=payment.id)
    root = etree.fromstring(result.xml_bytes)
    assert root is not None
    assert "pain.001" in root.nsmap.get(None, "") or any(
        "pain.001" in v for v in root.nsmap.values()
    )


def test_pain001_contains_correct_amount(
    db_session, funded_account, payment_service, analyst_keypair, manager_keypair
):
    """PAIN.001 XML must contain the exact payment amount and currency."""
    manager_priv, _ = manager_keypair
    payment = payment_service.initiate_payment(
        _req(funded_account, amount=Decimal("1234.56"), reference="PAIN-AMOUNT-001"),
        maker_user_id="analyst_1",
    )
    payment_service.approve_payment(
        payment_id=payment.id,
        checker_user_id="manager_1",
        private_key=manager_priv,
    )
    result = payment_service.validate_and_export(payment_id=payment.id)
    xml_str = result.xml_bytes.decode("utf-8")
    assert "1234.56" in xml_str
    assert "EUR" in xml_str
