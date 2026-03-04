"""Accounting Period Manager — lifecycle, year-end rollover, CT600 due-date calculation.

Satisfies:
- HMRC self-assessment (CT600): Period-end date determines filing deadlines —
  companies are required to file and pay within 9 months + 1 day of the period end
  (s.197 FA 1998 / Schedule 13 FA 1998). Quarterly instalments for large companies
  fall in months 7, 10, 13 and 16 from the start of the accounting period (QIPS rules).
- Period close authority: Soft close requires 'treasury_manager' role to confirm
  period-end balances; hard close requires 'system_admin' and records the responsible
  user for ISAE 3402 evidence. Once hard-closed, the period cannot be reopened without
  an explicit privileged override with audit reason written to the audit log.
- Year-end rollover: After hard-close of the final period in the financial year, retained
  earnings (account 3100) are swept to Retained Earnings B/F (account 3200) via an
  auto-generated and immediately posted 'year_end_rollover' journal, ready for the new year.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError, PeriodClosedError
from app.models import AccountingPeriod
from app.services.ledger_service import JournalCreate, JournalLineCreate, LedgerService

# HMRC Quarterly Instalment Payment (QIP) months from period start
_QIP_MONTHS = [7, 10, 13, 16]


# ─────────────────────────────────────────────────── Pydantic schemas ──────────

class AccountingPeriodCreate(BaseModel):
    period_name: str = Field(..., min_length=1, max_length=100)
    period_type: Literal["monthly", "quarterly", "annual"]
    period_start: date
    period_end: date
    is_year_end: bool = False
    is_large_company_for_ct: bool = False

    @model_validator(mode="after")
    def _validate_dates(self) -> "AccountingPeriodCreate":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start.")
        if (self.period_end - self.period_start).days > 366:
            raise ValueError("Accounting period may not exceed 12 months.")
        return self


class SoftCloseRequest(BaseModel):
    confirm: bool = Field(default=True)


class HardCloseRequest(BaseModel):
    confirm: bool = Field(default=True)
    close_reason: str = Field(..., min_length=5, max_length=500)


class ReopenRequest(BaseModel):
    reopen_reason: str = Field(..., min_length=10, max_length=500)


class YearEndRolloverRequest(BaseModel):
    period_id: uuid.UUID
    retained_earnings_account_id: uuid.UUID    # 3100 – Retained Earnings (current year)
    retained_earnings_bf_account_id: uuid.UUID  # 3200 – Retained Earnings B/F
    net_profit_for_year: Decimal
    journal_reference: str


class AccountingPeriodRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_id: uuid.UUID
    tenant_id: uuid.UUID
    period_name: str
    period_type: str
    period_start: date
    period_end: date
    is_year_end: bool
    is_large_company_for_ct: bool
    status: str
    soft_closed_by_user_id: uuid.UUID | None
    soft_closed_at: datetime | None
    hard_closed_by_user_id: uuid.UUID | None
    hard_closed_at: datetime | None
    ct600_due_date: date | None
    qip_due_dates: list[str] | None


class CtTaxDates(BaseModel):
    period_end: date
    ct600_due_date: date
    qip_due_dates: list[date]


# ─────────────────────────────────────────────────── Service ───────────────────

class AccountingPeriodService:
    """Accounting period lifecycle — open → soft_closed → hard_closed.

    Hard-closed periods are immutable for the purposes of financial reporting.
    Year-end rollover automatically sweeps retained earnings after hard close.
    """

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        user_roles: list[str] | None = None,
        user_ip: str = "",
    ) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._user_roles = user_roles or []
        self._user_ip = user_ip

    # ──────────────────────────────────────── CRUD ─────────────────────────────

    async def create_period(self, payload: AccountingPeriodCreate) -> AccountingPeriod:
        ct_due, qips = _compute_tax_dates(
            payload.period_end, large_company=payload.is_large_company_for_ct
        )
        period = AccountingPeriod(
            tenant_id=self._tenant_id,
            period_name=payload.period_name,
            period_type=payload.period_type,
            period_start=payload.period_start,
            period_end=payload.period_end,
            is_year_end=payload.is_year_end,
            is_large_company_for_ct=payload.is_large_company_for_ct,
            status="open",
            ct600_due_date=ct_due,
            qip_due_dates=[d.isoformat() for d in qips] if qips else None,
        )
        self._db.add(period)
        await self._db.flush()
        return period

    async def get_period(self, period_id: uuid.UUID) -> AccountingPeriod:
        return await self._get(period_id)

    async def list_periods(
        self, status: str | None = None
    ) -> list[AccountingPeriod]:
        stmt = select(AccountingPeriod).where(
            AccountingPeriod.tenant_id == self._tenant_id
        )
        if status:
            stmt = stmt.where(AccountingPeriod.status == status)
        result = await self._db.scalars(stmt.order_by(AccountingPeriod.period_start))
        return list(result.all())

    # ──────────────────────────────────────── Status transitions ───────────────

    async def soft_close(self, period_id: uuid.UUID) -> AccountingPeriod:
        """Soft-close — requires 'treasury_manager' or 'system_admin' role."""
        if not _has_any_role(self._user_roles, ["treasury_manager", "system_admin"]):
            raise PermissionDeniedError("soft_close requires treasury_manager role.")
        period = await self._get(period_id)
        if period.status != "open":
            raise PeriodClosedError(period.period_name)
        period.status = "soft_closed"
        period.soft_closed_by_user_id = self._user_id
        period.soft_closed_at = datetime.now(tz=timezone.utc)
        await self._db.flush()
        return period

    async def hard_close(
        self, period_id: uuid.UUID, request: HardCloseRequest,
    ) -> AccountingPeriod:
        """Hard-close — requires 'system_admin' role; reason is written to audit field."""
        if not _has_any_role(self._user_roles, ["system_admin"]):
            raise PermissionDeniedError("hard_close requires system_admin role.")
        period = await self._get(period_id)
        if period.status == "hard_closed":
            raise PeriodClosedError(period.period_name)
        period.status = "hard_closed"
        period.hard_closed_by_user_id = self._user_id
        period.hard_closed_at = datetime.now(tz=timezone.utc)
        period.hard_close_reason = request.close_reason
        await self._db.flush()
        return period

    async def reopen_period(
        self, period_id: uuid.UUID, request: ReopenRequest,
    ) -> AccountingPeriod:
        """Reopen hard-closed period — requires 'system_admin'; audit reason mandatory."""
        if not _has_any_role(self._user_roles, ["system_admin"]):
            raise PermissionDeniedError("reopen_period requires system_admin role.")
        period = await self._get(period_id)
        period.status = "open"
        period.reopen_reason = request.reopen_reason
        await self._db.flush()
        return period

    # ──────────────────────────────────────── Year-end rollover ────────────────

    async def year_end_rollover(
        self, request: YearEndRolloverRequest,
    ) -> uuid.UUID:
        """Sweep current-year retained earnings to B/F — posts year_end_rollover journal."""
        period = await self._get(request.period_id)
        if period.status != "hard_closed":
            raise ValueError(
                "Year-end rollover requires the period to be hard-closed first."
            )
        if not period.is_year_end:
            raise ValueError("This period is not marked as a year-end period.")

        amount = request.net_profit_for_year
        if amount >= 0:
            lines = [
                JournalLineCreate(
                    account_id=request.retained_earnings_account_id,
                    debit_amount=amount,
                    credit_amount=Decimal("0"),
                    currency_code="GBP",
                    description="Year-end sweep — retained earnings this year",
                    vat_treatment="T9",
                ),
                JournalLineCreate(
                    account_id=request.retained_earnings_bf_account_id,
                    debit_amount=Decimal("0"),
                    credit_amount=amount,
                    currency_code="GBP",
                    description="Year-end sweep — retained earnings B/F",
                    vat_treatment="T9",
                ),
            ]
        else:
            loss = abs(amount)
            lines = [
                JournalLineCreate(
                    account_id=request.retained_earnings_bf_account_id,
                    debit_amount=loss,
                    credit_amount=Decimal("0"),
                    currency_code="GBP",
                    description="Year-end sweep — accumulated loss to B/F",
                    vat_treatment="T9",
                ),
                JournalLineCreate(
                    account_id=request.retained_earnings_account_id,
                    debit_amount=Decimal("0"),
                    credit_amount=loss,
                    currency_code="GBP",
                    description="Year-end sweep — clear current-year retained earnings (loss)",
                    vat_treatment="T9",
                ),
            ]

        ledger_svc = LedgerService(self._db, self._tenant_id, self._user_id, self._user_ip)
        jnl = await ledger_svc.create_journal(
            JournalCreate(
                period_id=request.period_id,
                journal_reference=request.journal_reference,
                description=f"Year-end retained earnings rollover — period {period.period_name}",
                currency_code="GBP",
                lines=lines,
            ),
            journal_type="year_end_rollover",
        )
        await ledger_svc.post_journal(jnl.journal_id)
        return jnl.journal_id

    # ──────────────────────────────────────── CT date calculation ──────────────

    @staticmethod
    def compute_ct_dates(period_end: date, is_large_company: bool = False) -> CtTaxDates:
        """Return CT600 due date and, if large company, QIP instalment dates.

        CT600 due: 9 months + 1 day after period end (s.222(2) TMA 1970 via CTA 2009).
        QIP: Months 7, 10, 13, 16 from period start of the ACCOUNTING period
        (Corporation Tax (Instalment Payments) Regulations 1998 SI 1998/3175).
        """
        ct600, qips = _compute_tax_dates(period_end, large_company=is_large_company)
        return CtTaxDates(period_end=period_end, ct600_due_date=ct600, qip_due_dates=qips)

    # ──────────────────────────────────────── helpers ──────────────────────────

    async def _get(self, period_id: uuid.UUID) -> AccountingPeriod:
        result = await self._db.scalar(
            select(AccountingPeriod).where(
                AccountingPeriod.tenant_id == self._tenant_id,
                AccountingPeriod.period_id == period_id,
            )
        )
        if not result:
            raise NotFoundError("AccountingPeriod", period_id)
        return result


# ─────────────────────────────────────────────── pure functions ────────────────

def _compute_tax_dates(
    period_end: date, large_company: bool = False
) -> tuple[date, list[date]]:
    """Return (ct600_due_date, qip_dates). qip_dates is empty for non-large companies."""
    # CT600: 9 months and 1 day after period end
    # Add 9 months by going to year+0..1 month calculation
    m = period_end.month + 9
    y = period_end.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    try:
        ct600 = date(y, m, period_end.day) + timedelta(days=1)
    except ValueError:
        # Handle month-end edge: e.g. 31 Jan + 9 months → Oct 31 → Nov 1
        import calendar
        last_day = calendar.monthrange(y, m)[1]
        ct600 = date(y, m, min(period_end.day, last_day)) + timedelta(days=1)

    qip_dates: list[date] = []
    if large_company:
        # Period *start* is period_end - ~12 months; derive approximate period start
        # for QIP month offsets from period start
        period_start_approx = date(period_end.year - 1, period_end.month, 1)
        for months_offset in _QIP_MONTHS:
            m2 = period_start_approx.month + months_offset
            y2 = period_start_approx.year + (m2 - 1) // 12
            m2 = (m2 - 1) % 12 + 1
            try:
                qip_dates.append(date(y2, m2, period_start_approx.day))
            except ValueError:
                import calendar
                last_day = calendar.monthrange(y2, m2)[1]
                qip_dates.append(date(y2, m2, last_day))

    return ct600, qip_dates


def _has_any_role(user_roles: list[str], required: list[str]) -> bool:
    return bool(set(user_roles) & set(required))
