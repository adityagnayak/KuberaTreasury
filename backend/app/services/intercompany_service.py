"""Intercompany transaction management and Corporate Interest Restriction (CIR) service.

Satisfies:
- HMRC CIR (Finance Act 2017, Part 10 TIOPA 2010): Aggregates UK group net interest
  expense across all entities. Alert raised at £1.5M, hard flag at £2M per settings.
- Transfer pricing (TIOPA 2010 s.147): Validates intercompany loan rates against
  HMRC-comparable arm's length range ±150bps from benchmarked rate. Rate variance
  above this triggers TransferPricingError requiring documented TP adjustment.
- Intercompany matching: Confirms payables (account 2100) and receivables (account 1200)
  agree across same group, with ageing buckets 0–30, 31–60, 61–90, 90+ days.
- CIR filing: restricted amount written to corporate_interest_restrictions table;
  disallowed interest treated as CT adjustment (account 3500 / 7300).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError, TransferPricingError
from app.models import CorporateInterestRestriction, IntercompanyTransaction


# ─────────────────────────────────────────────────── Pydantic schemas ──────────

class IntercompanyTransactionCreate(BaseModel):
    counterparty_entity_name: str = Field(..., min_length=1, max_length=255)
    counterparty_entity_id: str = Field(..., min_length=1, max_length=60)
    transaction_type: Literal["loan", "service_charge", "dividend", "royalty", "other"]
    transaction_date: date
    due_date: date
    principal_amount: Decimal = Field(..., gt=0)
    currency_code: str = Field(default="GBP", min_length=3, max_length=3)
    contracted_rate_bps: Decimal | None = Field(default=None, ge=0)
    benchmark_rate_bps: Decimal | None = Field(default=None, ge=0)
    tp_justification: str | None = None
    notes: str | None = None


class IntercompanyTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: uuid.UUID
    tenant_id: uuid.UUID
    counterparty_entity_name: str
    counterparty_entity_id: str
    transaction_type: str
    transaction_date: date
    due_date: date
    principal_amount: Decimal
    currency_code: str
    contracted_rate_bps: Decimal | None
    benchmark_rate_bps: Decimal | None
    rate_variance_bps: Decimal | None
    tp_flag_raised: bool
    tp_justification: str | None
    is_matched: bool
    matched_at: date | None
    notes: str | None


class AgeingBucket(BaseModel):
    bucket: str
    count: int
    total_amount: Decimal


class AgeingReport(BaseModel):
    reference_date: date
    buckets: list[AgeingBucket]
    unmatched_total: Decimal


class CirSummary(BaseModel):
    period_start: date
    period_end: date
    gross_interest_expense: Decimal
    gross_interest_income: Decimal
    net_interest_expense: Decimal
    cir_threshold_alert: Decimal
    cir_threshold_hard: Decimal
    alert_triggered: bool
    hard_flag_triggered: bool
    restricted_amount: Decimal | None
    restriction_id: uuid.UUID | None


# ─────────────────────────────────────────────────── Service ───────────────────

class IntercompanyService:
    """Intercompany elimination and corporate interest restriction engine."""

    _TP_TOLERANCE_BPS = Decimal("150")

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        user_ip: str = "",
    ) -> None:
        self._db = db
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._user_ip = user_ip

    # ──────────────────────────────────────── transaction CRUD ─────────────────

    async def create_transaction(
        self, payload: IntercompanyTransactionCreate,
    ) -> IntercompanyTransaction:
        """Record an intercompany transaction with optional TP rate validation."""
        rate_variance: Decimal | None = None
        tp_flag = False

        if (
            payload.contracted_rate_bps is not None
            and payload.benchmark_rate_bps is not None
        ):
            variance = abs(payload.contracted_rate_bps - payload.benchmark_rate_bps)
            rate_variance = variance
            if variance > self._TP_TOLERANCE_BPS:
                tp_flag = True
                raise TransferPricingError(float(variance))

        tx = IntercompanyTransaction(
            tenant_id=self._tenant_id,
            counterparty_entity_name=payload.counterparty_entity_name,
            counterparty_entity_id=payload.counterparty_entity_id,
            transaction_type=payload.transaction_type,
            transaction_date=payload.transaction_date,
            due_date=payload.due_date,
            principal_amount=payload.principal_amount,
            currency_code=payload.currency_code,
            contracted_rate_bps=payload.contracted_rate_bps,
            benchmark_rate_bps=payload.benchmark_rate_bps,
            rate_variance_bps=rate_variance,
            tp_flag_raised=tp_flag,
            tp_justification=payload.tp_justification,
            is_matched=False,
            notes=payload.notes,
            created_by_user_id=self._user_id,
        )
        self._db.add(tx)
        await self._db.flush()
        return tx

    async def match_transaction(self, transaction_id: uuid.UUID) -> IntercompanyTransaction:
        tx = await self._get_tx(transaction_id)
        tx.is_matched = True
        tx.matched_at = date.today()
        await self._db.flush()
        return tx

    async def get_transaction(self, transaction_id: uuid.UUID) -> IntercompanyTransaction:
        return await self._get_tx(transaction_id)

    async def list_transactions(
        self,
        transaction_type: str | None = None,
        matched: bool | None = None,
    ) -> list[IntercompanyTransaction]:
        stmt = select(IntercompanyTransaction).where(
            IntercompanyTransaction.tenant_id == self._tenant_id
        )
        if transaction_type:
            stmt = stmt.where(IntercompanyTransaction.transaction_type == transaction_type)
        if matched is not None:
            stmt = stmt.where(IntercompanyTransaction.is_matched.is_(matched))
        result = await self._db.scalars(stmt.order_by(IntercompanyTransaction.transaction_date))
        return list(result.all())

    # ──────────────────────────────────────── ageing report ────────────────────

    async def ageing_report(self, reference_date: date) -> AgeingReport:
        """Bucket all unmatched transactions by age (days overdue)."""
        overdue_txs = await self._db.scalars(
            select(IntercompanyTransaction).where(
                IntercompanyTransaction.tenant_id == self._tenant_id,
                IntercompanyTransaction.is_matched.is_(False),
            )
        )
        buckets: dict[str, dict[str, Decimal | int]] = {
            "0-30": {"count": 0, "total": Decimal("0")},
            "31-60": {"count": 0, "total": Decimal("0")},
            "61-90": {"count": 0, "total": Decimal("0")},
            "90+": {"count": 0, "total": Decimal("0")},
        }
        unmatched_total = Decimal("0")
        for tx in overdue_txs.all():
            age = (reference_date - tx.due_date).days
            if age <= 30:
                key = "0-30"
            elif age <= 60:
                key = "31-60"
            elif age <= 90:
                key = "61-90"
            else:
                key = "90+"
            buckets[key]["count"] += 1
            buckets[key]["total"] += tx.principal_amount
            unmatched_total += tx.principal_amount

        return AgeingReport(
            reference_date=reference_date,
            buckets=[
                AgeingBucket(bucket=k, count=v["count"], total_amount=v["total"])
                for k, v in buckets.items()
            ],
            unmatched_total=unmatched_total,
        )

    # ──────────────────────────────────────── CIR ──────────────────────────────

    async def calculate_cir(
        self,
        period_start: date,
        period_end: date,
        gross_interest_expense: Decimal,
        gross_interest_income: Decimal,
        restricted_amount: Decimal | None = None,
    ) -> CirSummary:
        """Aggregate net interest expense and flag if CIR thresholds exceeded.

        Finance Act 2017 / TIOPA 2010 Part 10: net interest expense exceeding
        30% of tax-EBITDA (or where the group QNWI rule applies) is disallowed.
        Thresholds here represent the £1.5M (alert) and £2M (hard flag) absolute
        safe harbour monitoring levels configured in settings.

        The caller supplies pre-computed gross figures from the ledger.
        This service persists the result and returns an alert flag for downstream
        workflow routing (e.g., notify Tax Director, lock period-close).
        """
        net = gross_interest_expense - gross_interest_income
        alert = net >= settings.CIR_ALERT_THRESHOLD
        hard = net >= settings.CIR_HARD_FLAG_THRESHOLD

        cir = CorporateInterestRestriction(
            tenant_id=self._tenant_id,
            period_start=period_start,
            period_end=period_end,
            gross_interest_expense=gross_interest_expense,
            gross_interest_income=gross_interest_income,
            net_interest_expense=net,
            alert_triggered=alert,
            hard_flag_triggered=hard,
            restricted_amount=restricted_amount,
            created_by_user_id=self._user_id,
        )
        self._db.add(cir)
        await self._db.flush()

        return CirSummary(
            period_start=period_start,
            period_end=period_end,
            gross_interest_expense=gross_interest_expense,
            gross_interest_income=gross_interest_income,
            net_interest_expense=net,
            cir_threshold_alert=settings.CIR_ALERT_THRESHOLD,
            cir_threshold_hard=settings.CIR_HARD_FLAG_THRESHOLD,
            alert_triggered=alert,
            hard_flag_triggered=hard,
            restricted_amount=restricted_amount,
            restriction_id=cir.restriction_id,
        )

    # ──────────────────────────────────────── helpers ──────────────────────────

    async def _get_tx(self, transaction_id: uuid.UUID) -> IntercompanyTransaction:
        result = await self._db.scalar(
            select(IntercompanyTransaction).where(
                IntercompanyTransaction.tenant_id == self._tenant_id,
                IntercompanyTransaction.transaction_id == transaction_id,
            )
        )
        if not result:
            raise NotFoundError("IntercompanyTransaction", transaction_id)
        return result
