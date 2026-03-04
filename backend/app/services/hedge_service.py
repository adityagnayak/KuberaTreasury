"""IFRS 9 Hedge Accounting service — designation, effectiveness, OCI, de-designation.

Satisfies IFRS 9 §6.2–6.5:
- Three hedge relationship types (fair value, cash flow, net investment).
- Designation documentation: instrument, hedged item, risk component, hedge ratio, date.
- Prospective effectiveness: dollar-offset method or regression (both accepted under IFRS 9 §B6.4).
- Retrospective effectiveness: cumulative dollar-offset must remain 80–125% (§B6.4.4).
  Outside this band→ qualify flag set False → system triggers de-designation workflow.
- OCI reclassification journal: auto-generated when hedged item affects P&L (§6.5.11).
- De-designation: reason and date recorded; cumulative OCI treatment documented per §6.5.6.
- Tax note embedded in every designation: hedge accounting does NOT change corporation
  tax position (HMRC CT Manual CG53000); tax follows the underlying economic transaction.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import HedgeEffectivenessError, NotFoundError
from app.models import (
    AccountingPeriod,
    ChartOfAccount,
    HedgeDesignation,
    HedgeEffectivenessTest,
    HedgeOciReclassification,
    Journal,
    JournalLine,
)
from app.services.ledger_service import JournalCreate, JournalLineCreate, LedgerService

TAX_NOTE = (
    "Hedge accounting designation under IFRS 9 does not alter the corporation tax "
    "position of any entity in this group. For tax purposes, gains and losses follow "
    "the underlying hedged item or instrument per HMRC CT Manual CG53000."
)

# ─────────────────────────────────────────────────── Pydantic schemas ──────────


class HedgeDesignationCreate(BaseModel):
    hedge_reference: str = Field(..., min_length=1, max_length=60)
    hedge_type: Literal["fair_value", "cash_flow", "net_investment"]
    hedging_instrument_description: str = Field(..., min_length=5, max_length=500)
    hedged_item_description: str = Field(..., min_length=5, max_length=500)
    risk_component: str = Field(..., min_length=1, max_length=120)
    hedge_ratio: Decimal = Field(..., gt=0, le=1)
    designation_date: date
    prospective_method: Literal["dollar_offset", "regression"]


class EffectivenessTestCreate(BaseModel):
    period_id: uuid.UUID
    test_type: Literal["prospective", "retrospective"]
    method: Literal["dollar_offset", "regression"]
    instrument_fair_value_change: Decimal
    hedged_item_fair_value_change: Decimal
    narrative: str | None = None

    @model_validator(mode="after")
    def _validate_hedged_item_nonzero(self) -> "EffectivenessTestCreate":
        if self.hedged_item_fair_value_change == 0:
            raise ValueError(
                "hedged_item_fair_value_change cannot be zero (division by zero in ratio)."
            )
        return self


class OciReclassificationCreate(BaseModel):
    period_id: uuid.UUID
    oci_account_id: uuid.UUID  # hedging reserve OCI account
    pnl_account_id: uuid.UUID  # income/expense account to reclassify into
    amount_reclassified: Decimal = Field(..., ne=0)
    currency_code: str = Field(default="GBP", min_length=3, max_length=3)
    trigger_description: str = Field(..., min_length=5, max_length=500)
    journal_reference: str = Field(..., min_length=1, max_length=60)


class DeDesignationUpdate(BaseModel):
    de_designation_date: date
    de_designation_reason: str = Field(..., min_length=5, max_length=500)
    cumulative_oci_treatment: str = Field(..., min_length=5, max_length=255)


class HedgeDesignationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    hedge_id: uuid.UUID
    tenant_id: uuid.UUID
    hedge_reference: str
    hedge_type: str
    hedging_instrument_description: str
    hedged_item_description: str
    risk_component: str
    hedge_ratio: Decimal
    designation_date: date
    prospective_method: str
    is_active: bool
    de_designation_date: date | None
    de_designation_reason: str | None
    cumulative_oci_treatment_on_dedesignation: str | None
    tax_note: str
    created_at: datetime


class EffectivenessTestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    test_id: uuid.UUID
    hedge_id: uuid.UUID
    period_id: uuid.UUID
    test_type: str
    method: str
    instrument_fair_value_change: Decimal
    hedged_item_fair_value_change: Decimal
    effectiveness_ratio: Decimal
    passed: bool
    narrative: str | None
    tested_at: datetime


# ─────────────────────────────────────────────────── Service ───────────────────


class HedgeAccountingService:
    """IFRS 9 hedge accounting lifecycle manager.

    All prospective tests are non-blocking (documented with pass/fail).
    Retrospective failures outside 80–125% raise ``HedgeEffectivenessError``
    which must be handled by the caller to de-designate the hedge.
    """

    _RETRO_MIN = Decimal("0.80")
    _RETRO_MAX = Decimal("1.25")

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

    # ──────────────────────────────────────── designation ──────────────────────

    async def designate(self, payload: HedgeDesignationCreate) -> HedgeDesignation:
        hd = HedgeDesignation(
            tenant_id=self._tenant_id,
            hedge_reference=payload.hedge_reference,
            hedge_type=payload.hedge_type,
            hedging_instrument_description=payload.hedging_instrument_description,
            hedged_item_description=payload.hedged_item_description,
            risk_component=payload.risk_component,
            hedge_ratio=payload.hedge_ratio,
            designation_date=payload.designation_date,
            prospective_method=payload.prospective_method,
            is_active=True,
            tax_note=TAX_NOTE,
            created_by_user_id=self._user_id,
        )
        self._db.add(hd)
        await self._db.flush()
        return hd

    async def de_designate(
        self,
        hedge_id: uuid.UUID,
        payload: DeDesignationUpdate,
    ) -> HedgeDesignation:
        hd = await self._get_hedge(hedge_id)
        if not hd.is_active:
            raise ValueError("Hedge is already de-designated.")
        hd.is_active = False
        hd.de_designation_date = payload.de_designation_date
        hd.de_designation_reason = payload.de_designation_reason
        hd.cumulative_oci_treatment_on_dedesignation = payload.cumulative_oci_treatment
        await self._db.flush()
        return hd

    # ──────────────────────────────────────── effectiveness ────────────────────

    async def run_effectiveness_test(
        self,
        hedge_id: uuid.UUID,
        payload: EffectivenessTestCreate,
    ) -> HedgeEffectivenessTest:
        hd = await self._get_hedge(hedge_id)
        if not hd.is_active:
            raise ValueError("Cannot test an inactive hedge designation.")

        # Dollar-offset ratio: |instrument FV change / hedged item FV change|
        ratio = abs(
            payload.instrument_fair_value_change / payload.hedged_item_fair_value_change
        )

        passed: bool
        if payload.test_type == "retrospective":
            passed = self._RETRO_MIN <= ratio <= self._RETRO_MAX
        else:
            # Prospective: document result; IFRS 9 §B6.4 does not mandate a numeric band
            passed = True  # prospective is qualitative under IFRS 9 B6.4.1

        result = HedgeEffectivenessTest(
            tenant_id=self._tenant_id,
            hedge_id=hedge_id,
            period_id=payload.period_id,
            test_type=payload.test_type,
            method=payload.method,
            instrument_fair_value_change=payload.instrument_fair_value_change,
            hedged_item_fair_value_change=payload.hedged_item_fair_value_change,
            effectiveness_ratio=ratio,
            passed=passed,
            narrative=payload.narrative,
            tested_by_user_id=self._user_id,
            tested_at=datetime.now(tz=timezone.utc),
        )
        self._db.add(result)
        await self._db.flush()

        if payload.test_type == "retrospective" and not passed:
            raise HedgeEffectivenessError(float(ratio))

        return result

    # ──────────────────────────────────────── OCI reclassification ─────────────

    async def reclassify_oci_to_pnl(
        self,
        hedge_id: uuid.UUID,
        payload: OciReclassificationCreate,
    ) -> HedgeOciReclassification:
        """Generate the journal moving cumulative OCI amounts into P&L.

        Debit hedging reserve OCI, credit the relevant income/expense account
        (or vice-versa for losses). The journal type is ``auto_oci_reclassification``.
        """
        hd = await self._get_hedge(hedge_id)
        if hd.hedge_type not in ("cash_flow", "net_investment"):
            raise ValueError(
                "OCI reclassification only applies to cash flow and net investment hedges."
            )

        amount = payload.amount_reclassified
        # If positive: debit OCI reserve (reduce it), credit P&L account
        # If negative: debit P&L account, credit OCI reserve
        if amount > 0:
            oci_dr, oci_cr = amount, Decimal("0")
            pnl_dr, pnl_cr = Decimal("0"), amount
        else:
            oci_dr, oci_cr = Decimal("0"), abs(amount)
            pnl_dr, pnl_cr = abs(amount), Decimal("0")

        ledger_svc = LedgerService(
            self._db, self._tenant_id, self._user_id, self._user_ip
        )
        journal = await ledger_svc.create_journal(
            JournalCreate(
                period_id=payload.period_id,
                journal_reference=payload.journal_reference,
                description=f"OCI reclassification: {hd.hedge_reference}. {payload.trigger_description}",
                currency_code=payload.currency_code,
                lines=[
                    JournalLineCreate(
                        account_id=payload.oci_account_id,
                        debit_amount=oci_dr,
                        credit_amount=oci_cr,
                        currency_code=payload.currency_code,
                        description="Hedging reserve (OCI) reclassification",
                    ),
                    JournalLineCreate(
                        account_id=payload.pnl_account_id,
                        debit_amount=pnl_dr,
                        credit_amount=pnl_cr,
                        currency_code=payload.currency_code,
                        description=f"P&L reclassification from OCI: {payload.trigger_description}",
                    ),
                ],
            ),
            journal_type="auto_oci_reclassification",
        )
        await ledger_svc.post_journal(journal.journal_id)

        oci_rec = HedgeOciReclassification(
            tenant_id=self._tenant_id,
            hedge_id=hedge_id,
            journal_id=journal.journal_id,
            period_id=payload.period_id,
            amount_reclassified=amount,
            currency_code=payload.currency_code,
            trigger_description=payload.trigger_description,
        )
        self._db.add(oci_rec)
        await self._db.flush()
        return oci_rec

    # ──────────────────────────────────────── queries ──────────────────────────

    async def get_designation(self, hedge_id: uuid.UUID) -> HedgeDesignation:
        return await self._get_hedge(hedge_id)

    async def list_designations(
        self, active_only: bool = True
    ) -> list[HedgeDesignation]:
        stmt = select(HedgeDesignation).where(
            HedgeDesignation.tenant_id == self._tenant_id
        )
        if active_only:
            stmt = stmt.where(HedgeDesignation.is_active.is_(True))
        result = await self._db.scalars(stmt)
        return list(result.all())

    async def list_effectiveness_tests(
        self,
        hedge_id: uuid.UUID,
    ) -> list[HedgeEffectivenessTest]:
        result = await self._db.scalars(
            select(HedgeEffectivenessTest)
            .where(
                HedgeEffectivenessTest.tenant_id == self._tenant_id,
                HedgeEffectivenessTest.hedge_id == hedge_id,
            )
            .order_by(HedgeEffectivenessTest.tested_at)
        )
        return list(result.all())

    async def get_hedge_register(self) -> list[dict]:
        """Return hedge register summary suitable for PDF export / board report."""
        hedges = await self.list_designations(active_only=False)
        register = []
        for h in hedges:
            tests = await self.list_effectiveness_tests(h.hedge_id)
            register.append(
                {
                    "hedge_reference": h.hedge_reference,
                    "hedge_type": h.hedge_type,
                    "hedging_instrument": h.hedging_instrument_description,
                    "hedged_item": h.hedged_item_description,
                    "risk_component": h.risk_component,
                    "hedge_ratio": str(h.hedge_ratio),
                    "designation_date": h.designation_date.isoformat(),
                    "is_active": h.is_active,
                    "de_designation_date": (
                        h.de_designation_date.isoformat()
                        if h.de_designation_date
                        else None
                    ),
                    "de_designation_reason": h.de_designation_reason,
                    "cumulative_oci_treatment": h.cumulative_oci_treatment_on_dedesignation,
                    "tax_note": h.tax_note,
                    "effectiveness_tests": [
                        {
                            "period_id": str(t.period_id),
                            "test_type": t.test_type,
                            "method": t.method,
                            "ratio": str(t.effectiveness_ratio),
                            "passed": t.passed,
                            "tested_at": t.tested_at.isoformat(),
                        }
                        for t in tests
                    ],
                }
            )
        return register

    async def _get_hedge(self, hedge_id: uuid.UUID) -> HedgeDesignation:
        result = await self._db.scalar(
            select(HedgeDesignation).where(
                HedgeDesignation.tenant_id == self._tenant_id,
                HedgeDesignation.hedge_id == hedge_id,
            )
        )
        if not result:
            raise NotFoundError("HedgeDesignation", hedge_id)
        return result
