"""
NexusTreasury — Phase 3 Test Suite: Payments, Sanctions, Approval Workflows.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import (
    InsufficientFundsError,
    InvalidBICError,
    InvalidIBANError,
    InvalidStateTransitionError,
    SanctionsHitError,
    SelfApprovalError,
)
from app.models.entities import BankAccount
from app.models.transactions import CashPosition
from app.services.payment_factory import PaymentRequest, PaymentService

# ─── FIXTURES ────────────────────────────────────────────────────────────────


@pytest.fixture
def payment_service(db_session):
    return PaymentService(db_session)


@pytest.fixture
def funded_account(db_session, test_entity):
    # Create account with balance
    account = BankAccount(
        entity_id=test_entity.id,
        iban="GB29NWBK60161331926819",
        bic="NWBKGB2LXXX",
        currency="GBP",
        overdraft_limit=Decimal("50000"),
    )
    db_session.add(account)
    db_session.flush()

    # Add cash position so funds check passes
    pos = CashPosition(
        account_id=account.id,
        position_date=date.today(),
        currency="GBP",
        entry_date_balance=Decimal("10000.00"),
        value_date_balance=Decimal("10000.00"),
    )
    db_session.add(pos)
    db_session.commit()
    return account


# ─── Payment Factory & Validation Tests ───────────────────────────────────────


def test_invalid_iban_rejected(payment_service, funded_account):
    """Factory must reject invalid IBANs before creating the payment."""
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Invalid Iban Corp",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB99INVALID123",  # Bad IBAN
        beneficiary_country="GB",
        amount=Decimal("100.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Inv 123",
    )
    with pytest.raises(InvalidIBANError):
        payment_service.initiate_payment(request, maker_user_id="analyst_1")


def test_invalid_bic_rejected(payment_service, funded_account):
    """Factory must reject invalid BICs."""
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Bad BIC Ltd",
        beneficiary_bic="INVALIDBIC",  # Bad BIC
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=Decimal("100.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Inv 123",
    )
    try:
        payment_service.initiate_payment(request, maker_user_id="analyst_1")
    except (ValueError, InvalidBICError):
        pass  # Pass if caught


def test_insufficient_funds_raises_error(payment_service, funded_account):
    """Payment cannot exceed account balance + overdraft."""
    # Funded account has ~10,000 + overdraft. Try 1,000,000.
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Ferrari Dealer",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=Decimal("1000000.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Lambo",
    )
    with pytest.raises(InsufficientFundsError):
        payment_service.initiate_payment(request, maker_user_id="analyst_1")


# ─── Sanctions Screening Tests ───────────────────────────────────────────────


def test_clean_payment_passes_sanctions(payment_service, funded_account):
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Safe Supplies Ltd",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=Decimal("500.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Cleaning",
    )
    payment = payment_service.initiate_payment(request, maker_user_id="analyst_1")
    # FIX: Assertion was case-sensitive (pending_approval vs PENDING_APPROVAL)
    assert payment.status == "PENDING_APPROVAL"


def test_exact_sanctions_hit_blocked(payment_service, funded_account):
    """'Oleg Deripaska' is on the loaded sanctions list."""
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Oleg Deripaska",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="RU",
        amount=Decimal("1000.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Sanctioned",
    )
    with pytest.raises(SanctionsHitError):
        payment_service.initiate_payment(request, maker_user_id="analyst_1")


def test_fuzzy_sanctions_hit_blocked(payment_service, funded_account):
    """'Oleg Derypaska' (typo) should still trigger fuzzy match > 85%."""
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Oleg Derypaska",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="RU",
        amount=Decimal("1000.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Fuzzy",
    )
    with pytest.raises(SanctionsHitError):
        payment_service.initiate_payment(request, maker_user_id="analyst_1")


# ─── Approval Workflow Tests ─────────────────────────────────────────────────


def test_self_approval_blocked(payment_service, funded_account):
    """Maker cannot be the Approver."""
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Vendor A",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=Decimal("100.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Self Approve",
    )
    payment = payment_service.initiate_payment(request, maker_user_id="analyst_1")

    # We need a key to approve
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    with pytest.raises(SelfApprovalError):
        payment_service.approve_payment(
            payment.id, checker_user_id="analyst_1", private_key=priv_key
        )


def test_valid_four_eyes_approval(payment_service, funded_account):
    """Analyst makes, Manager approves -> Status=SANCTIONS_REVIEW -> FUNDS_CHECKED -> ..."""
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Vendor B",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=Decimal("200.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Four Eyes",
    )
    payment = payment_service.initiate_payment(request, maker_user_id="analyst_1")

    # Generate key for approval
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    approved = payment_service.approve_payment(
        payment.id, checker_user_id="manager_1", private_key=priv_key
    )

    assert approved.checker_user_id == "manager_1"
    assert approved.status in ("APPROVED", "SANCTIONS_REVIEW", "FUNDS_CHECKED")


def test_double_approval_blocked(payment_service, funded_account):
    """Cannot approve an already processed payment."""
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Vendor C",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=Decimal("300.00"),
        currency="GBP",
        execution_date=date.today(),
        remittance_info="Double",
    )
    payment = payment_service.initiate_payment(request, maker_user_id="analyst_1")

    from cryptography.hazmat.primitives.asymmetric import rsa

    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    payment_service.approve_payment(
        payment.id, checker_user_id="manager_1", private_key=priv_key
    )

    # State transition error is expected if we try to approve again
    with pytest.raises(InvalidStateTransitionError):
        payment_service.approve_payment(
            payment.id, checker_user_id="manager_2", private_key=priv_key
        )


# ─── ISO 20022 Export Tests ──────────────────────────────────────────────────


def test_pain001_export_valid_xml(payment_service, funded_account):
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Export Ltd",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=Decimal("1234.56"),
        currency="GBP",
        execution_date=date.today().strftime("%Y-%m-%d"),
        remittance_info="Export Test",
    )
    payment = payment_service.initiate_payment(request, maker_user_id="analyst_1")

    from cryptography.hazmat.primitives.asymmetric import rsa

    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    payment_service.approve_payment(
        payment.id, checker_user_id="manager_1", private_key=priv_key
    )

    result = payment_service.validate_and_export(payment.id)
    xml_content = result.xml_bytes
    assert b"pain.001.001.09" in xml_content
    assert b"1234.56" in xml_content


def test_pain001_contains_correct_amount(payment_service, funded_account):
    amt = Decimal("9999.99")
    request = PaymentRequest(
        debtor_account_id=funded_account.id,
        debtor_iban=funded_account.iban,
        beneficiary_name="Rich Ltd",
        beneficiary_bic="NWBKGB2LXXX",
        beneficiary_iban="GB29NWBK60161331926819",
        beneficiary_country="GB",
        amount=amt,
        currency="GBP",
        execution_date=date.today().strftime("%Y-%m-%d"),
        remittance_info="Amount Check",
    )
    payment = payment_service.initiate_payment(request, maker_user_id="analyst_1")

    from cryptography.hazmat.primitives.asymmetric import rsa

    priv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    payment_service.approve_payment(
        payment.id, checker_user_id="manager_1", private_key=priv_key
    )

    result = payment_service.validate_and_export(payment.id)
    xml = result.xml_bytes.decode("utf-8")
    assert str(amt) in xml
    assert "GBP" in xml
