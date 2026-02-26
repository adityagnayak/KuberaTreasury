"""
NexusTreasury — Phase 5 Test Suite: Concurrency, E-BAM, RBAC
FIX:
  Concurrency: Added robust retries for SQLite 'database is locked' errors,
               checking rowcount to verify update success.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import OperationalError

from app.core.exceptions import (
    ExpiredMandateError,
    MandateKeyMismatchError,
    NoMandateError,
    PermissionDeniedError,
)
from app.models.entities import BankAccount, Entity
from app.models.mandates import KYCDocument
from app.services.ebam import EBAMService
from app.services.rbac import RBACService

# ─── RBAC Tests ───────────────────────────────────────────────────────────────


@pytest.fixture
def rbac():
    return RBACService()


class TestRBAC:
    def test_analyst_can_read(self, rbac):
        # treasury_analyst can READ transactions
        assert (
            rbac.check(role="treasury_analyst", action="READ", resource="transactions")
            is True
        )

    def test_analyst_cannot_approve_payment(self, rbac):
        # treasury_analyst is explicitly denied approve_payment
        assert (
            rbac.has_permission(
                role="treasury_analyst", action="WRITE", resource="approve_payment"
            )
            is False
        )

    def test_manager_can_approve_payment(self, rbac):
        assert (
            rbac.check(
                role="treasury_manager", action="WRITE", resource="approve_payment"
            )
            is True
        )

    def test_auditor_read_only(self, rbac):
        assert (
            rbac.check(role="auditor", action="READ", resource="transactions") is True
        )
        # auditor has WRITE:* in deny set
        assert (
            rbac.has_permission(
                role="auditor", action="WRITE", resource="initiate_payment"
            )
            is False
        )

    def test_admin_has_all_permissions(self, rbac):
        # system_admin has READ:* and WRITE:* wildcards
        for action, resource in [
            ("READ", "transactions"),
            ("WRITE", "approve_payment"),
            ("WRITE", "mandates"),
            ("READ", "audit_logs"),
        ]:
            assert (
                rbac.check(role="system_admin", action=action, resource=resource)
                is True
            )

    def test_unknown_role_denied(self, rbac):
        # "guest" is not in ROLE_PERMISSIONS → raises PermissionDeniedError
        assert (
            rbac.has_permission(role="guest", action="READ", resource="transactions")
            is False
        )

    def test_unknown_permission_denied(self, rbac):
        # system_admin wildcards cover READ:* and WRITE:*, "NUKE" is not in allow set
        assert (
            rbac.has_permission(
                role="treasury_analyst", action="DELETE", resource="transactions"
            )
            is False
        )

    def test_permission_denied_exception(self, rbac):
        # check() (not has_permission) raises PermissionDeniedError on deny
        with pytest.raises(PermissionDeniedError):
            rbac.check(
                role="treasury_analyst", action="WRITE", resource="approve_payment"
            )

    def test_permission_granted_no_exception(self, rbac):
        # Should not raise
        rbac.check(role="treasury_manager", action="WRITE", resource="approve_payment")

    def test_explicit_deny_overrides_wildcard(self, rbac):
        # auditor deny set has WRITE:* so WRITE:initiate_payment is denied
        assert (
            rbac.has_permission(
                role="auditor", action="WRITE", resource="initiate_payment"
            )
            is False
        )


# ─── E-BAM Tests ──────────────────────────────────────────────────────────────


@pytest.fixture
def ebam_entity(db_session):
    entity = Entity(name="EBAM Test Corp", entity_type="parent", base_currency="EUR")
    db_session.add(entity)
    db_session.flush()
    db_session.commit()
    return entity


@pytest.fixture
def ebam_account(db_session, ebam_entity):
    account = BankAccount(
        entity_id=ebam_entity.id,
        iban="DE89370400440532013300",
        bic="COBADEFFXXX",
        currency="EUR",
        overdraft_limit=Decimal("0"),
    )
    db_session.add(account)
    db_session.commit()
    return account


@pytest.fixture
def ebam_service(db_session):
    return EBAMService(db_session)


class TestEBAM:
    def test_mandate_creation(
        self, db_session, ebam_account, ebam_service, analyst_keypair
    ):
        _, pub_key = analyst_keypair  # (priv, pub) from conftest
        mandate = ebam_service.create_mandate(
            account_id=ebam_account.id,
            signatory_name="Analyst One",
            signatory_user_id="user_analyst_1",
            public_key=pub_key,  # RSAPublicKey object
            valid_from=date.today(),
            valid_until=date.today() + timedelta(days=365),
        )
        assert mandate.id is not None
        assert mandate.status == "active"  # lowercase in the service

    def test_expired_mandate_raises_error(
        self, db_session, ebam_account, ebam_service, analyst_keypair
    ):
        _, pub_key = analyst_keypair
        # Create an already-expired mandate
        ebam_service.create_mandate(
            account_id=ebam_account.id,
            signatory_name="Expired User",
            signatory_user_id="user_expired_1",
            public_key=pub_key,
            valid_from=date.today() - timedelta(days=400),
            valid_until=date.today() - timedelta(days=10),
        )
        # validate_payment_mandate raises ExpiredMandateError when all mandates are expired
        with pytest.raises(ExpiredMandateError):
            ebam_service.validate_payment_mandate(account_id=ebam_account.id)

    def test_no_mandate_raises_error(self, db_session, ebam_account, ebam_service):
        # No mandate exists → NoMandateError
        with pytest.raises(NoMandateError):
            ebam_service.validate_payment_mandate(account_id=ebam_account.id)

    def test_key_mismatch_raises_error(
        self, db_session, ebam_account, ebam_service, analyst_keypair, manager_keypair
    ):
        _, analyst_pub = analyst_keypair
        _, manager_pub = manager_keypair

        # Create mandate with analyst's key
        ebam_service.create_mandate(
            account_id=ebam_account.id,
            signatory_name="Analyst",
            signatory_user_id="user_mismatch_1",
            public_key=analyst_pub,
            valid_from=date.today(),
            valid_until=date.today() + timedelta(days=365),
        )

        # Validate with manager's key → MandateKeyMismatchError
        from cryptography.hazmat.primitives import serialization

        manager_pem = manager_pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        with pytest.raises(MandateKeyMismatchError):
            ebam_service.validate_payment_mandate(
                account_id=ebam_account.id,
                checker_public_key_pem=manager_pem,
            )

    def test_mandate_revocation(
        self, db_session, ebam_account, ebam_service, analyst_keypair
    ):
        _, pub_key = analyst_keypair
        mandate = ebam_service.create_mandate(
            account_id=ebam_account.id,
            signatory_name="Revoke User",
            signatory_user_id="user_revoke_1",
            public_key=pub_key,
            valid_from=date.today(),
            valid_until=date.today() + timedelta(days=365),
        )
        ebam_service.revoke_mandate(
            mandate_id=mandate.id,
            revoking_user_id="admin_1",
        )
        db_session.refresh(mandate)
        assert mandate.status == "revoked"

        # Now there are no active mandates → NoMandateError
        with pytest.raises((NoMandateError, ExpiredMandateError)):
            ebam_service.validate_payment_mandate(account_id=ebam_account.id)

    def test_kyc_document_attached(
        self, db_session, ebam_entity, ebam_account, ebam_service, analyst_keypair
    ):
        _, pub_key = analyst_keypair
        ebam_service.create_mandate(
            account_id=ebam_account.id,
            signatory_name="KYC User",
            signatory_user_id="user_kyc_1",
            public_key=pub_key,
            valid_from=date.today(),
            valid_until=date.today() + timedelta(days=365),
        )
        # register_kyc_document takes entity_id, doc_type, doc_bytes
        ebam_service.register_kyc_document(
            entity_id=ebam_entity.id,
            doc_type="PASSPORT",
            doc_bytes=b"fake_passport_data_abc123",
            expiry_date=date.today() + timedelta(days=1825),
        )
        docs = db_session.query(KYCDocument).filter_by(entity_id=ebam_entity.id).all()
        assert len(docs) == 1
        assert docs[0].doc_type == "PASSPORT"

    def test_expiry_alerts_generated(
        self, db_session, ebam_account, ebam_service, analyst_keypair
    ):
        _, pub_key = analyst_keypair
        ebam_service.create_mandate(
            account_id=ebam_account.id,
            signatory_name="Expiring User",
            signatory_user_id="user_expiring_1",
            public_key=pub_key,
            valid_from=date.today() - timedelta(days=340),
            valid_until=date.today() + timedelta(days=25),
        )
        alerts = ebam_service.check_upcoming_expirations(days_ahead=30)
        assert len(alerts) >= 1
        # ExpirationAlert.detail contains "Signatory: {signatory_name}"
        assert any("Expiring User" in a.detail for a in alerts)


# ─── Concurrency Tests ────────────────────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_position_updates_consistent(self, session_factory):
        from app.models.transactions import CashPosition

        with session_factory() as session:
            entity = Entity(
                name="Concurrency Corp", entity_type="parent", base_currency="EUR"
            )
            session.add(entity)
            session.flush()
            account = BankAccount(
                entity_id=entity.id,
                iban=f"DE89370400440532{str(uuid.uuid4().int)[:8]}",
                bic="COBADEFFXXX",
                currency="EUR",
                overdraft_limit=Decimal("0"),
            )
            session.add(account)
            session.flush()
            pos = CashPosition(
                account_id=account.id,
                position_date=date.today(),
                value_date_balance=Decimal("10000.00"),
                entry_date_balance=Decimal("10000.00"),
                currency="EUR",
            )
            session.add(pos)
            session.commit()
            pos_id = pos.id

        errors = []
        results = []

        def update_balance(delta):
            # Attempt to update with retries for SQLite locking
            # We verify rowcount to ensuring the update actually happened
            for attempt in range(10):
                try:
                    with session_factory() as session:
                        from sqlalchemy import text

                        # Explicit transaction needed for SQLite locking behavior check
                        result = session.execute(
                            text(
                                "UPDATE cash_positions SET value_date_balance = value_date_balance + :delta WHERE id = :id"
                            ),
                            {"delta": str(delta), "id": pos_id},
                        )
                        session.commit()
                        if result.rowcount > 0:
                            results.append(delta)
                            return
                        else:
                            # rowcount 0 means no row found, which shouldn't happen here unless deleted
                            # or transaction visibility issue. We can treat as retryable or error.
                            errors.append(f"Update rowcount=0 for delta {delta}")
                            return
                except OperationalError as e:
                    if "locked" in str(e).lower():
                        time.sleep(0.1 + (attempt * 0.05))  # Linear backoff
                        continue
                    errors.append(str(e))
                    return
                except Exception as e:
                    errors.append(str(e))
                    return
            errors.append(f"Max retries exceeded for delta {delta}")

        threads = [
            threading.Thread(
                target=update_balance,
                args=(Decimal("500.00"),),
            ),
            threading.Thread(
                target=update_balance,
                args=(Decimal("-200.00"),),
            ),
            threading.Thread(
                target=update_balance,
                args=(Decimal("100.00"),),
            ),
        ]

        # Small stagger to reduce initial collision
        for t in threads:
            t.start()
            time.sleep(0.01)

        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent update errors: {errors}"
        # Extra check: Ensure all 3 updates were recorded
        assert len(results) == 3, f"Expected 3 updates, got {len(results)}"

        with session_factory() as session:
            from app.models.transactions import CashPosition as CP

            final_pos = session.query(CP).get(pos_id)
            expected = (
                Decimal("10000.00")
                + Decimal("500.00")
                + Decimal("-200.00")
                + Decimal("100.00")
            )
            assert final_pos.value_date_balance == expected

    def test_duplicate_statement_concurrent_protection(self, session_factory):
        from app.core.exceptions import DuplicateStatementError
        from app.services.ingestion import StatementIngestionService
        from tests.conftest import build_sample_camt053

        iban = f"DE89370400440532{str(uuid.uuid4().int)[:8]}"
        with session_factory() as session:
            entity = Entity(
                name="Concurrent Dup Corp", entity_type="parent", base_currency="EUR"
            )
            session.add(entity)
            session.flush()
            account = BankAccount(
                entity_id=entity.id,
                iban=iban,
                bic="COBADEFFXXX",
                currency="EUR",
                overdraft_limit=Decimal("0"),
            )
            session.add(account)
            session.commit()

        xml_bytes = build_sample_camt053(
            "CONC-DUP-001",
            iban,
            "2024-01-15",
            [{"amount": "100.00", "cdi": "CRDT", "trn": "CONC-TRN-001"}],
        )

        successes = []
        errors = []

        def ingest():
            for attempt in range(5):
                try:
                    svc = StatementIngestionService(session_factory())
                    svc.ingest_camt053(xml_bytes, "concurrent_user")
                    successes.append(True)
                    return
                except DuplicateStatementError:
                    errors.append("duplicate")
                    return
                except OperationalError as e:
                    if "locked" in str(e).lower():
                        time.sleep(0.05)
                        continue
                    errors.append(str(e))
                    return
                except Exception as e:
                    errors.append(str(e))
                    return

        threads = [threading.Thread(target=ingest) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1
        assert len([e for e in errors if e == "duplicate"]) == 2
