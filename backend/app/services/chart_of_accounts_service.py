"""Chart of Accounts service with UK standard seeder and HMRC nominal mappings.

Satisfies: HMRC nominal code requirement, VAT treatment flag per account,
treasury-specific account types (cash pools, intercompany loans, FX reserve,
hedging reserve OCI, interest payable/receivable, CIR adjustment).
All queries are scoped to tenant_id — no cross-tenant data leakage.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.models import ChartOfAccount


# ─────────────────────────────────────────────────── Pydantic schemas ──────────

class AccountCreate(BaseModel):
    account_code: str = Field(..., min_length=1, max_length=30)
    account_name: str = Field(..., min_length=1, max_length=255)
    account_type: Literal[
        "asset", "liability", "equity", "income", "expense"
    ]
    account_subtype: str | None = None
    currency_code: str = Field(default="GBP", min_length=3, max_length=3)
    hmrc_nominal_code: str | None = Field(default=None, max_length=10)
    vat_treatment: Literal["T0", "T1", "T2", "T4", "T7", "T9"] | None = None
    is_treasury_account: bool = False
    allows_currency_revaluation: bool = False
    parent_account_id: uuid.UUID | None = None


class AccountUpdate(BaseModel):
    account_name: str | None = None
    hmrc_nominal_code: str | None = None
    vat_treatment: Literal["T0", "T1", "T2", "T4", "T7", "T9"] | None = None
    is_treasury_account: bool | None = None
    allows_currency_revaluation: bool | None = None
    is_active: bool | None = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: uuid.UUID
    tenant_id: uuid.UUID
    account_code: str
    account_name: str
    account_type: str
    account_subtype: str | None
    currency_code: str
    hmrc_nominal_code: str | None
    vat_treatment: str | None
    is_treasury_account: bool
    allows_currency_revaluation: bool
    parent_account_id: uuid.UUID | None
    is_active: bool


# ─────────────────────────────────────── UK standard seeder data ───────────────
# Format: (account_code, account_name, account_type, account_subtype,
#          hmrc_nominal_code, vat_treatment, is_treasury, allows_reval)
UK_STANDARD_COA: list[tuple] = [
    # ── Assets ─────────────────────────────────────────────────────────────
    ("1000", "Cash at Bank — GBP", "asset", "current_asset", "1000", "T9", True, False),
    ("1010", "Cash at Bank — USD", "asset", "current_asset", "1010", "T9", True, True),
    ("1020", "Cash at Bank — EUR", "asset", "current_asset", "1020", "T9", True, True),
    ("1030", "Cash Pool — Group Notional", "asset", "cash_pool", "1030", "T9", True, False),
    ("1100", "Trade Debtors", "asset", "current_asset", "1100", "T0", False, False),
    ("1101", "VAT Receivable (Input Tax)", "asset", "current_asset", "2202", "T9", False, False),
    ("1200", "Intercompany Receivables", "asset", "current_asset", "1200", "T9", True, False),
    ("1210", "Intercompany Loan Receivable", "asset", "non_current_asset", "1210", "T9", True, False),
    ("1300", "Prepayments", "asset", "current_asset", "1300", "T9", False, False),
    ("1400", "Other Debtors", "asset", "current_asset", "1400", "T0", False, False),
    ("1500", "Interest Receivable", "asset", "interest_receivable", "1500", "T9", True, False),
    ("1900", "Fixed Assets — Plant & Equipment", "asset", "non_current_asset", "0030", "T9", False, False),
    ("1910", "Accumulated Depreciation — Fixed Assets", "asset", "non_current_asset", "0040", "T9", False, False),
    # ── Liabilities ────────────────────────────────────────────────────────
    ("2000", "Trade Creditors", "liability", "current_liability", "2100", "T0", False, False),
    ("2001", "VAT Payable (Output Tax)", "liability", "current_liability", "2200", "T9", False, False),
    ("2002", "PAYE / NIC Payable", "liability", "current_liability", "7003", "T9", False, False),
    ("2003", "CIS Deductions Payable", "liability", "current_liability", "7007", "T9", False, False),
    ("2100", "Intercompany Payables", "liability", "current_liability", "2100", "T9", True, False),
    ("2110", "Intercompany Loan Payable", "liability", "non_current_liability", "2110", "T9", True, False),
    ("2200", "Interest Payable", "liability", "interest_payable", "7902", "T9", True, False),
    ("2300", "Accruals", "liability", "current_liability", "2300", "T9", False, False),
    ("2400", "Corporation Tax Payable", "liability", "current_liability", "2300", "T9", False, False),
    ("2500", "Short-Term Borrowings", "liability", "current_liability", "2300", "T9", True, False),
    ("2600", "Long-Term Borrowings", "liability", "non_current_liability", "2600", "T9", True, False),
    # ── Equity ─────────────────────────────────────────────────────────────
    ("3000", "Share Capital", "equity", "share_capital", "3000", "T9", False, False),
    ("3100", "Share Premium", "equity", "share_capital", "3100", "T9", False, False),
    ("3200", "Retained Earnings", "equity", "retained_earnings", "3200", "T9", False, False),
    ("3300", "FX Revaluation Reserve", "equity", "fx_revaluation_reserve", "3300", "T9", True, False),
    ("3400", "Hedging Reserve (OCI — IFRS 9)", "equity", "hedging_reserve_oci", "3400", "T9", True, False),
    ("3500", "CIR Adjustment Account", "equity", "cir_adjustment", "3500", "T9", True, False),
    # ── Income ─────────────────────────────────────────────────────────────
    ("4000", "Turnover — Products (Standard Rate)", "income", "revenue", "4000", "T0", False, False),
    ("4001", "Turnover — Services (Standard Rate)", "income", "revenue", "4001", "T0", False, False),
    ("4002", "Turnover — Zero Rated Sales", "income", "revenue", "4002", "T4", False, False),
    ("4003", "Turnover — Exempt Sales", "income", "revenue", "4003", "T2", False, False),
    ("4004", "Turnover — Outside Scope", "income", "revenue", "4004", "T9", False, False),
    ("4100", "Interest Income", "income", "finance_income", "4100", "T9", True, False),
    ("4110", "FX Gains", "income", "finance_income", "4110", "T9", True, False),
    ("4200", "Other Income", "income", "revenue", "4200", "T0", False, False),
    # ── Expenses ───────────────────────────────────────────────────────────
    ("5000", "Cost of Sales", "expense", "cost_of_sales", "5000", "T0", False, False),
    ("6000", "Staff Costs — Salaries", "expense", "operating_expense", "7000", "T9", False, False),
    ("6001", "Employers NIC", "expense", "operating_expense", "7006", "T9", False, False),
    ("6100", "Rent & Rates", "expense", "operating_expense", "7100", "T0", False, False),
    ("6200", "Utilities", "expense", "operating_expense", "7200", "T0", False, False),
    ("6300", "Professional Fees", "expense", "operating_expense", "7600", "T0", False, False),
    ("7000", "Interest Expense", "expense", "finance_expense", "7900", "T9", True, False),
    ("7001", "FX Losses", "expense", "finance_expense", "7901", "T9", True, False),
    ("7100", "Depreciation", "expense", "operating_expense", "8000", "T9", False, False),
    ("7200", "Corporation Tax Charge", "expense", "tax_payable", "8600", "T9", False, False),
    ("7300", "CIR Restriction Charge", "expense", "cir_adjustment", "8601", "T9", True, False),
]

# ─────────────────────────────────────────────────── Service ───────────────────

class ChartOfAccountsService:
    """Business logic for the UK chart of accounts.

    HMRC compliance note: every account is mapped to an HMRC nominal code
    following HMRC's standard nominal ledger designations. VAT treatment
    follows HMRC VAT Notice 700 codes (T0–T9). Multi-tenant guard on every
    method ensures no cross-tenant access.
    """

    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def seed_uk_standard(self) -> list[ChartOfAccount]:
        """Insert the full UK standard CoA for a new tenant (idempotent)."""
        created: list[ChartOfAccount] = []
        for (code, name, actype, subtype, hmrc, vat, is_treas, reval) in UK_STANDARD_COA:
            existing = await self._db.scalar(
                select(ChartOfAccount).where(
                    ChartOfAccount.tenant_id == self._tenant_id,
                    ChartOfAccount.account_code == code,
                )
            )
            if existing:
                continue
            obj = ChartOfAccount(
                tenant_id=self._tenant_id,
                account_code=code,
                account_name=name,
                account_type=actype,
                account_subtype=subtype,
                currency_code="GBP",
                hmrc_nominal_code=hmrc,
                vat_treatment=vat,
                is_treasury_account=is_treas,
                allows_currency_revaluation=reval,
            )
            self._db.add(obj)
            created.append(obj)
        await self._db.flush()
        return created

    async def create(self, payload: AccountCreate) -> ChartOfAccount:
        obj = ChartOfAccount(
            tenant_id=self._tenant_id,
            **payload.model_dump(),
        )
        self._db.add(obj)
        await self._db.flush()
        return obj

    async def get(self, account_id: uuid.UUID) -> ChartOfAccount:
        obj = await self._db.scalar(
            select(ChartOfAccount).where(
                ChartOfAccount.tenant_id == self._tenant_id,
                ChartOfAccount.account_id == account_id,
            )
        )
        if not obj:
            raise NotFoundError("Account", account_id)
        return obj

    async def list_all(
        self,
        *,
        account_type: str | None = None,
        is_treasury: bool | None = None,
        active_only: bool = True,
    ) -> list[ChartOfAccount]:
        stmt = select(ChartOfAccount).where(ChartOfAccount.tenant_id == self._tenant_id)
        if account_type:
            stmt = stmt.where(ChartOfAccount.account_type == account_type)
        if is_treasury is not None:
            stmt = stmt.where(ChartOfAccount.is_treasury_account == is_treasury)
        if active_only:
            stmt = stmt.where(ChartOfAccount.is_active.is_(True))
        result = await self._db.scalars(stmt)
        return list(result.all())

    async def update(self, account_id: uuid.UUID, payload: AccountUpdate) -> ChartOfAccount:
        obj = await self.get(account_id)
        for k, v in payload.model_dump(exclude_none=True).items():
            setattr(obj, k, v)
        await self._db.flush()
        return obj

    async def deactivate(self, account_id: uuid.UUID) -> ChartOfAccount:
        obj = await self.get(account_id)
        obj.is_active = False
        await self._db.flush()
        return obj
