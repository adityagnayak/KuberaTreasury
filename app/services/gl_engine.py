"""
NexusTreasury — Double-Entry General Ledger Engine (Phase 4)
Maps treasury events to balanced journal entries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, getcontext
from typing import Dict, List, Optional

from app.core.exceptions import UnbalancedJournalError

getcontext().prec = 28

# ─── Chart of Accounts ────────────────────────────────────────────────────────

ACCOUNTS: Dict[str, str] = {
    "1000": "Bank_Account",
    "1100": "Accounts_Receivable",
    "1200": "Interest_Receivable",
    "1300": "Forward_Contract_Asset",
    "1400": "FX_Revaluation_Account",
    "2000": "Accounts_Payable",
    "2100": "Loan_Payable",
    "3000": "OCI_Hedging_Reserve",
    "4000": "Interest_Income",
    "4100": "Unrealized_FX_PnL",
    "5000": "Interest_Expense",
}

ACCOUNT_CODE: Dict[str, str] = {v: k for k, v in ACCOUNTS.items()}


# ─── Journal data types ───────────────────────────────────────────────────────


@dataclass
class JournalLine:
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    currency: str
    description: str = ""


@dataclass
class JournalEntry:
    entry_id: str
    event_type: str
    event_id: str
    lines: List[JournalLine]
    posting_date: datetime
    balanced: bool


@dataclass
class TreasuryEvent:
    event_id: str
    event_type: str  # PAYMENT_SENT | PAYMENT_RECEIVED | FX_REVALUATION |
    # INTEREST_ACCRUAL | LOAN_DRAWDOWN | LOAN_REPAYMENT |
    # HEDGE_FAIR_VALUE_CHANGE
    amount: Decimal
    currency: str
    metadata: Dict


# ─── GL Mapping Engine ────────────────────────────────────────────────────────


class GLMappingEngine:
    """Maps treasury events to balanced double-entry journal entries."""

    def __init__(self) -> None:
        self._journal: List[JournalEntry] = []

    def _line(
        self,
        account_name: str,
        debit: Decimal,
        credit: Decimal,
        currency: str,
        description: str = "",
    ) -> JournalLine:
        code = ACCOUNT_CODE.get(account_name, "9999")
        return JournalLine(
            account_code=code,
            account_name=account_name,
            debit=debit,
            credit=credit,
            currency=currency,
            description=description,
        )

    def _assert_balanced(self, lines: List[JournalLine]) -> None:
        total_debit = sum(l.debit for l in lines)
        total_credit = sum(l.credit for l in lines)
        if total_debit != total_credit:
            raise UnbalancedJournalError(total_debit, total_credit)

    # ── Event handlers ────────────────────────────────────────────────────────

    def _handle_payment_sent(self, event: TreasuryEvent) -> List[JournalLine]:
        amt, ccy = event.amount, event.currency
        return [
            self._line("Accounts_Payable", amt, Decimal("0"), ccy, "AP cleared"),
            self._line("Bank_Account", Decimal("0"), amt, ccy, "Cash out"),
        ]

    def _handle_payment_received(self, event: TreasuryEvent) -> List[JournalLine]:
        amt, ccy = event.amount, event.currency
        return [
            self._line("Bank_Account", amt, Decimal("0"), ccy, "Cash in"),
            self._line("Accounts_Receivable", Decimal("0"), amt, ccy, "AR cleared"),
        ]

    def _handle_fx_revaluation(self, event: TreasuryEvent) -> List[JournalLine]:
        gl = event.metadata.get("gain_loss", event.amount)
        direction = event.metadata.get("direction", "GAIN")
        ccy = event.currency
        if direction == "GAIN":
            return [
                self._line("FX_Revaluation_Account", gl, Decimal("0"), ccy),
                self._line("Unrealized_FX_PnL", Decimal("0"), gl, ccy),
            ]
        return [
            self._line("Unrealized_FX_PnL", gl, Decimal("0"), ccy),
            self._line("FX_Revaluation_Account", Decimal("0"), gl, ccy),
        ]

    def _handle_interest_accrual(self, event: TreasuryEvent) -> List[JournalLine]:
        """
        Positive rate: Dr Interest_Receivable / Cr Interest_Income
        Negative rate: Dr Interest_Income / Cr Interest_Receivable  (REVERSED)
        """
        amt = abs(event.amount)
        ccy = event.currency
        is_negative = event.metadata.get(
            "negative_rate", False
        ) or event.amount < Decimal("0")
        if not is_negative:
            return [
                self._line("Interest_Receivable", amt, Decimal("0"), ccy),
                self._line("Interest_Income", Decimal("0"), amt, ccy),
            ]
        return [
            self._line(
                "Interest_Income", amt, Decimal("0"), ccy, "Negative rate reversal"
            ),
            self._line(
                "Interest_Receivable", Decimal("0"), amt, ccy, "Negative rate reversal"
            ),
        ]

    def _handle_loan_drawdown(self, event: TreasuryEvent) -> List[JournalLine]:
        amt, ccy = event.amount, event.currency
        return [
            self._line(
                "Bank_Account", amt, Decimal("0"), ccy, "Loan proceeds received"
            ),
            self._line(
                "Loan_Payable", Decimal("0"), amt, ccy, "Loan liability created"
            ),
        ]

    def _handle_loan_repayment(self, event: TreasuryEvent) -> List[JournalLine]:
        principal = event.metadata.get("principal", event.amount)
        interest = event.metadata.get("interest", Decimal("0"))
        total = principal + interest
        ccy = event.currency
        return [
            self._line("Loan_Payable", principal, Decimal("0"), ccy),
            self._line("Interest_Expense", interest, Decimal("0"), ccy),
            self._line("Bank_Account", Decimal("0"), total, ccy),
        ]

    def _handle_hedge_fair_value_change(
        self, event: TreasuryEvent
    ) -> List[JournalLine]:
        amt = event.amount
        direction = event.metadata.get("direction", "INCREASE")
        ccy = event.currency
        if direction == "INCREASE":
            return [
                self._line("Forward_Contract_Asset", amt, Decimal("0"), ccy),
                self._line("OCI_Hedging_Reserve", Decimal("0"), amt, ccy),
            ]
        return [
            self._line("OCI_Hedging_Reserve", amt, Decimal("0"), ccy),
            self._line("Forward_Contract_Asset", Decimal("0"), amt, ccy),
        ]

    # ── Main entry point ──────────────────────────────────────────────────────

    def post_journal(self, event: TreasuryEvent) -> JournalEntry:
        handlers = {
            "PAYMENT_SENT": self._handle_payment_sent,
            "PAYMENT_RECEIVED": self._handle_payment_received,
            "FX_REVALUATION": self._handle_fx_revaluation,
            "INTEREST_ACCRUAL": self._handle_interest_accrual,
            "LOAN_DRAWDOWN": self._handle_loan_drawdown,
            "LOAN_REPAYMENT": self._handle_loan_repayment,
            "HEDGE_FAIR_VALUE_CHANGE": self._handle_hedge_fair_value_change,
        }
        handler = handlers.get(event.event_type)
        if handler is None:
            raise ValueError(f"Unknown event type: {event.event_type}")

        lines = handler(event)
        self._assert_balanced(lines)

        entry = JournalEntry(
            entry_id=str(uuid.uuid4()),
            event_type=event.event_type,
            event_id=event.event_id,
            lines=lines,
            posting_date=datetime.utcnow(),
            balanced=True,
        )
        self._journal.append(entry)
        return entry

    def get_journal(self) -> List[JournalEntry]:
        return list(self._journal)
