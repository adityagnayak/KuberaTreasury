#!/usr/bin/env python3
"""
Seed NexusTreasury with demo data for local development.
"""

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Import all models first so SQLAlchemy can resolve all relationships
from app.database import SessionLocal
from app.models.entities import BankAccount, Entity
from app.models.forecasts import ForecastEntry, VarianceAlert
from app.models.instruments import FXForward, GLJournalEntry, Loan
from app.models.mandates import KYCDocument, Mandate
from app.models.payments import Payment, SanctionsAlert
from app.models.transactions import CashPosition, Transaction


def generate_rsa_public_key_pem() -> str:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


def main():
    print("Seeding demo data...")

    session = SessionLocal()
    try:
        # ── Entities ──────────────────────────────────────────────────────────
        parent = Entity(
            name="NexusTreasury Demo Group",
            entity_type="parent",
            base_currency="EUR",
        )
        session.add(parent)

        sub_de = Entity(
            name="NexusTreasury Germany GmbH",
            entity_type="subsidiary",
            base_currency="EUR",
        )
        session.add(sub_de)

        sub_uk = Entity(
            name="NexusTreasury UK Ltd",
            entity_type="subsidiary",
            base_currency="GBP",
        )
        session.add(sub_uk)
        session.flush()

        # ── Bank Accounts ─────────────────────────────────────────────────────
        accounts_data = [
            (parent.id, "DE89370400440532013000", "COBADEFFXXX", "EUR", "0"),
            (parent.id, "GB29NWBK60161331926819", "NWBKGB2LXXX", "GBP", "10000"),
            (parent.id, "US12345678901234567890", "CITIUS33XXX", "USD", "50000"),
            (sub_de.id, "DE75512108001245126199", "SSKMDEMM", "EUR", "5000"),
            (sub_uk.id, "GB82WEST12345698765432", "WESTGB2LXXX", "GBP", "2000"),
        ]

        accounts = []
        for entity_id, iban, bic, ccy, overdraft in accounts_data:
            a = BankAccount(
                entity_id=entity_id,
                iban=iban,
                bic=bic,
                currency=ccy,
                overdraft_limit=Decimal(overdraft),
            )
            session.add(a)
            accounts.append(a)

        session.flush()

        # ── Cash Positions ─────────────────────────────────────────────────────
        balances = [
            Decimal("2500000.00"),
            Decimal("850000.00"),
            Decimal("1200000.00"),
            Decimal("450000.00"),
            Decimal("320000.00"),
        ]

        for acct, balance in zip(accounts, balances):
            for offset in range(5):
                pos = CashPosition(
                    account_id=acct.id,
                    position_date=date.today() - timedelta(days=offset),
                    value_date_balance=balance,
                    entry_date_balance=balance,
                    currency=acct.currency,
                )
                session.add(pos)

        session.flush()

        # ── Mandates ──────────────────────────────────────────────────────────
        signatories = [
            ("CFO", "user_cfo", 365),
            ("Treasurer", "user_treasurer", 365),
            ("Analyst", "user_analyst", 180),
        ]

        for account in accounts[:2]:
            for sig_name, sig_user_id, validity_days in signatories:
                mandate = Mandate(
                    account_id=account.id,
                    signatory_name=sig_name,
                    signatory_user_id=sig_user_id,
                    public_key_pem=generate_rsa_public_key_pem(),
                    valid_from=date.today(),
                    valid_until=date.today() + timedelta(days=validity_days),
                    status="active",
                )
                session.add(mandate)

        session.commit()
        print(f"Created {len(accounts)} bank accounts across 3 entities.")
        print("Seeded 5 days of cash positions per account.")
        print("Created mandates for 2 accounts with 3 signatories each.")
        print("\nDemo credentials (use in API calls):")
        print("  Signatories: user_cfo, user_treasurer, user_analyst")
        print("\nSeed complete!")
    finally:
        session.close()


if __name__ == "__main__":
    main()
