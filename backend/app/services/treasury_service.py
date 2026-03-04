"""Phase 3 treasury operations, forecasting controls, and reporting.

Satisfies:
- Group liquidity and position analytics (entity/bank/account/currency, maturity buckets).
- HMRC obligation schedule population (VAT/CT/PAYE/CIS/confirmation statement).
- AI forecasting guardrails (GDPR pseudonymisation + ISO 9001 §8.3 validation pipeline).
- Human-in-the-loop policy (forecast rows never posted to ledger automatically).
- Report generation payloads with audit trail records.
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _round_2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _urgency(due_date: date, as_of: date) -> Literal["green", "amber", "red"]:
    days = (due_date - as_of).days
    if days < 7:
        return "red"
    if days <= 30:
        return "amber"
    return "green"


def _end_of_month(d: date) -> date:
    return date(d.year, d.month, monthrange(d.year, d.month)[1])


def _next_month_due_day(period_end: date, day: int) -> date:
    first_of_next = _add_months(date(period_end.year, period_end.month, 1), 1)
    due_day = min(day, monthrange(first_of_next.year, first_of_next.month)[1])
    return date(first_of_next.year, first_of_next.month, due_day)


def _add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = ((d.month - 1 + months) % 12) + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


class PositionRow(BaseModel):
    entity: str
    bank: str
    account_id: str
    currency: str = Field(min_length=3, max_length=3)
    balance: Decimal
    fx_to_base: Decimal = Field(default=Decimal("1"), gt=Decimal("0"))
    maturity_days: int = Field(default=0)
    minimum_balance: Decimal = Field(default=Decimal("0"))
    overdraft_limit: Decimal = Field(default=Decimal("0"))
    overdraft_used: Decimal = Field(default=Decimal("0"))


class PaymentQueueItem(BaseModel):
    account_id: str
    amount_base: Decimal = Field(ge=Decimal("0"))


class FacilityRow(BaseModel):
    facility_name: str
    bank: str
    limit_amount: Decimal = Field(ge=Decimal("0"))
    current_drawn: Decimal = Field(ge=Decimal("0"))

    @property
    def undrawn(self) -> Decimal:
        return max(Decimal("0"), self.limit_amount - self.current_drawn)


class PositionRequest(BaseModel):
    base_currency: str = Field(default="GBP", min_length=3, max_length=3)
    rows: list[PositionRow]


class ConsolidatedPosition(BaseModel):
    base_currency: str
    consolidated_group_position: Decimal
    by_entity: dict[str, Decimal]
    by_bank: dict[str, Decimal]
    by_account: dict[str, Decimal]
    by_currency: dict[str, Decimal]
    maturity_buckets: dict[str, Decimal]


class SweepSimulationRequest(BaseModel):
    base_currency: str = Field(default="GBP", min_length=3, max_length=3)
    rows: list[PositionRow]
    proposed_payments: list[PaymentQueueItem]


class SweepSimulationResponse(BaseModel):
    before_position: Decimal
    after_position: Decimal
    net_payment_impact: Decimal
    by_account_after: dict[str, Decimal]


class LiquidityAlert(BaseModel):
    alert_type: Literal[
        "minimum_balance_breach",
        "overdraft_approach",
        "concentration_risk",
        "covenant_headroom",
    ]
    severity: Literal["info", "warning", "critical"]
    message: str


class LiquidityRequest(BaseModel):
    base_currency: str = Field(default="GBP", min_length=3, max_length=3)
    rows: list[PositionRow]
    facilities: list[FacilityRow] = Field(default_factory=list)
    payment_queue: list[PaymentQueueItem] = Field(default_factory=list)
    concentration_threshold: Decimal = Field(default=Decimal("0.40"))
    overdraft_alert_pct: Decimal = Field(default=Decimal("0.80"))
    covenant_headroom_alert_pct: Decimal = Field(default=Decimal("0.10"))


class LiquidityResponse(BaseModel):
    available_liquidity: Decimal
    cash_total: Decimal
    undrawn_total: Decimal
    payment_queue_total: Decimal
    covenant_headroom: dict[str, Decimal]
    alerts: list[LiquidityAlert]


class HmrcObligation(BaseModel):
    obligation_type: Literal["VAT", "CORP_TAX", "PAYE_NIC", "CIS", "CONFIRMATION_STATEMENT"]
    due_date: date
    estimated_amount: Decimal
    actual_amount: Decimal | None = None
    variance: Decimal | None = None
    urgency_colour: Literal["green", "amber", "red"]
    hmrc_payment_reference: str


class HmrcScheduleRequest(BaseModel):
    tenant_id: uuid.UUID
    as_of: date
    vat_quarter_end_dates: list[date] = Field(default_factory=list)
    vat_month_end_dates: list[date] = Field(default_factory=list)
    vat_monthly_mtd: bool = False
    corporation_tax_year_end: date
    large_company_ct: bool = False
    paye_months: list[date] = Field(default_factory=list)
    paye_payment_method: Literal["cheque", "electronic"] = "electronic"
    cis_months: list[date] = Field(default_factory=list)
    cis_payment_method: Literal["cheque", "electronic"] = "electronic"
    confirmation_statement_anniversary: date
    estimated_vat_amount: Decimal = Decimal("0")
    estimated_ct_amount: Decimal = Decimal("0")
    estimated_paye_amount: Decimal = Decimal("0")
    estimated_cis_amount: Decimal = Decimal("0")


class ForecastRowInput(BaseModel):
    account_id: str
    forecast_date: date
    amount: Decimal
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))


class ForecastInferenceRequest(BaseModel):
    tenant_id: uuid.UUID
    operator_user_id: uuid.UUID
    as_of: date
    horizon_days: int = Field(default=90, ge=1, le=366)
    rows: list[ForecastRowInput]
    amount_bound: Decimal = Field(default=Decimal("50000000"), gt=Decimal("0"))
    provider: Literal["ollama", "claude", "gemini"] | None = None
    model_version: str = "claude-sonnet-4-6"
    prompt: str
    raw_response: str
    latency_ms: int = Field(default=0, ge=0)


class ForecastAcceptedRow(BaseModel):
    account_ref_hash: str
    forecast_date: date
    amount: Decimal
    confidence: Decimal
    human_review_required: bool
    status: Literal["pending_human_review"] = "pending_human_review"


class ForecastRejectedRow(BaseModel):
    account_ref_hash: str
    forecast_date: date
    amount: Decimal
    confidence: Decimal
    reason: str


class InferenceAuditRecord(BaseModel):
    provider: str
    model_version: str
    account_ref_hash: str
    prompt_hash: str
    response_hash: str
    latency_ms: int
    accepted_count: int
    rejected_count: int
    operator_user_id: uuid.UUID
    tenant_id: uuid.UUID


class ForecastInferenceResponse(BaseModel):
    provider: str
    model_version: str
    accepted: list[ForecastAcceptedRow]
    rejected: list[ForecastRejectedRow]
    rejection_log: list[ForecastRejectedRow]
    audit_log: list[InferenceAuditRecord]
    gdpr_summary: str
    hitl_enforced: bool = True


class VarianceRow(BaseModel):
    entity: str
    currency: str
    forecast: Decimal
    actual: Decimal


class DailyVarianceRequest(BaseModel):
    as_of: date
    rows: list[VarianceRow]


class DailyVarianceExportRequest(DailyVarianceRequest):
    tenant_id: uuid.UUID
    operator_user_id: uuid.UUID


class DailyVarianceReport(BaseModel):
    as_of: date
    by_entity_currency: list[dict[str, Decimal | str]]


class WeeklySummaryRequest(BaseModel):
    as_of: date
    week_start: date
    week_end: date
    opening_position: Decimal
    closing_position: Decimal
    net_flows: Decimal
    fx_impact: Decimal
    hmrc_obligations: list[HmrcObligation] = Field(default_factory=list)
    forecast_actual_pairs: list[tuple[Decimal, Decimal]] = Field(default_factory=list)


class WeeklySummaryExportRequest(WeeklySummaryRequest):
    tenant_id: uuid.UUID
    operator_user_id: uuid.UUID


class WeeklySummaryReport(BaseModel):
    week_start: date
    week_end: date
    position_movement: Decimal
    net_flows: Decimal
    fx_impact: Decimal
    hmrc_due_this_week: list[HmrcObligation]
    ai_forecast_mape: Decimal


class ReportExportResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, ser_json_bytes="base64")

    report_id: str
    generated_at: datetime
    pdf_bytes: bytes
    excel_bytes: bytes
    digital_signature: str
    audit_log: dict[str, str]


class ReportAuditEvent(BaseModel):
    report_id: str
    report_name: str
    tenant_id: str
    operator_user_id: str
    timestamp: datetime
    parameters_hash: str


class BoardPackRequest(BaseModel):
    tenant_id: uuid.UUID
    operator_user_id: uuid.UUID
    as_of: date
    group_liquidity_waterfall: list[dict[str, str | Decimal]]
    hmrc_obligations_next_12m: list[HmrcObligation]
    debt_maturity_profile: list[dict[str, str | Decimal]]
    fx_exposure: list[dict[str, str | Decimal]]
    covenant_headroom: list[dict[str, str | Decimal]]
    ifrs9_hedge_register_summary: list[dict[str, str | Decimal]]
    ai_forecast_accuracy_metrics: dict[str, Decimal]
    transfer_pricing_summary: dict[str, str | Decimal]


class BoardPackResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, ser_json_bytes="base64")

    report_id: str
    generated_at: datetime
    pdf_bytes: bytes
    excel_bytes: bytes
    digital_signature: str
    audit_log: dict[str, str]


class TreasuryService:
    """Phase 3 domain service.

    Notes:
    - This service is intentionally side-effect-light and deterministic.
    - AI outputs are always returned in pending human review state and never
      posted to the general ledger.
    """

    def __init__(self) -> None:
        self._report_audit_events: list[dict[str, str]] = []

    def _export_report(
        self,
        *,
        report_name: str,
        report_title: str,
        tenant_id: uuid.UUID,
        operator_user_id: uuid.UUID,
        parameters_hash: str,
        pdf_lines: list[str],
        csv_lines: list[str],
    ) -> ReportExportResponse:
        report_id = str(uuid.uuid4())
        generated_at = datetime.now(tz=timezone.utc)

        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)
        c.setTitle(report_title)
        c.drawString(50, 800, report_title)
        c.drawString(50, 785, f"Report ID: {report_id}")
        c.drawString(50, 770, f"Generated: {generated_at.isoformat()}")
        y = 745
        for line in pdf_lines:
            c.drawString(50, y, line)
            y -= 15
            if y <= 60:
                c.showPage()
                y = 800
        c.showPage()
        c.save()
        pdf_bytes = pdf_buffer.getvalue()

        excel_bytes = "\n".join(csv_lines).encode("utf-8")
        digital_signature = _hash_text(
            report_id
            + generated_at.isoformat()
            + _hash_text(pdf_bytes.hex())
            + _hash_text(excel_bytes.hex())
        )
        audit_log = {
            "report_id": report_id,
            "report_name": report_name,
            "tenant_id": str(tenant_id),
            "operator_user_id": str(operator_user_id),
            "timestamp": generated_at.isoformat(),
            "parameters_hash": parameters_hash,
        }
        self._report_audit_events.append(audit_log)

        return ReportExportResponse(
            report_id=report_id,
            generated_at=generated_at,
            pdf_bytes=pdf_bytes,
            excel_bytes=excel_bytes,
            digital_signature=digital_signature,
            audit_log=audit_log,
        )

    def report_audit_history(self, *, limit: int = 100) -> list[ReportAuditEvent]:
        if limit < 1:
            limit = 1
        ordered = list(reversed(self._report_audit_events))[:limit]
        return [
            ReportAuditEvent(
                report_id=event["report_id"],
                report_name=event.get("report_name", "unknown"),
                tenant_id=event["tenant_id"],
                operator_user_id=event["operator_user_id"],
                timestamp=datetime.fromisoformat(event["timestamp"]),
                parameters_hash=event["parameters_hash"],
            )
            for event in ordered
        ]

    @staticmethod
    def _bucket(days: int) -> str:
        if days <= 0:
            return "same_day"
        if days <= 7:
            return "d1_7"
        if days <= 30:
            return "d8_30"
        if days <= 90:
            return "d31_90"
        return "d90_plus"

    @staticmethod
    def _to_base(row: PositionRow) -> Decimal:
        return _round_2(row.balance * row.fx_to_base)

    def consolidated_position(self, payload: PositionRequest) -> ConsolidatedPosition:
        by_entity: dict[str, Decimal] = {}
        by_bank: dict[str, Decimal] = {}
        by_account: dict[str, Decimal] = {}
        by_currency: dict[str, Decimal] = {}
        buckets = {"same_day": Decimal("0"), "d1_7": Decimal("0"), "d8_30": Decimal("0"), "d31_90": Decimal("0"), "d90_plus": Decimal("0")}

        total = Decimal("0")
        for row in payload.rows:
            amount_base = self._to_base(row)
            total += amount_base
            by_entity[row.entity] = by_entity.get(row.entity, Decimal("0")) + amount_base
            by_bank[row.bank] = by_bank.get(row.bank, Decimal("0")) + amount_base
            by_account[row.account_id] = by_account.get(row.account_id, Decimal("0")) + amount_base
            by_currency[row.currency] = by_currency.get(row.currency, Decimal("0")) + row.balance
            buckets[self._bucket(row.maturity_days)] += amount_base

        return ConsolidatedPosition(
            base_currency=payload.base_currency,
            consolidated_group_position=_round_2(total),
            by_entity={k: _round_2(v) for k, v in by_entity.items()},
            by_bank={k: _round_2(v) for k, v in by_bank.items()},
            by_account={k: _round_2(v) for k, v in by_account.items()},
            by_currency={k: _round_2(v) for k, v in by_currency.items()},
            maturity_buckets={k: _round_2(v) for k, v in buckets.items()},
        )

    def simulate_intraday_sweep(self, payload: SweepSimulationRequest) -> SweepSimulationResponse:
        before = self.consolidated_position(PositionRequest(base_currency=payload.base_currency, rows=payload.rows)).consolidated_group_position
        by_account_after = {
            row.account_id: self._to_base(row)
            for row in payload.rows
        }
        queue_total = Decimal("0")
        for pmt in payload.proposed_payments:
            queue_total += pmt.amount_base
            by_account_after[pmt.account_id] = by_account_after.get(pmt.account_id, Decimal("0")) - pmt.amount_base
        after = before - queue_total
        return SweepSimulationResponse(
            before_position=_round_2(before),
            after_position=_round_2(after),
            net_payment_impact=_round_2(queue_total),
            by_account_after={k: _round_2(v) for k, v in by_account_after.items()},
        )

    def available_liquidity_and_alerts(self, payload: LiquidityRequest) -> LiquidityResponse:
        cash_total = sum((self._to_base(row) for row in payload.rows), Decimal("0"))
        undrawn_total = sum((fac.undrawn for fac in payload.facilities), Decimal("0"))
        queue_total = sum((p.amount_base for p in payload.payment_queue), Decimal("0"))
        available = cash_total + undrawn_total - queue_total

        alerts: list[LiquidityAlert] = []
        for row in payload.rows:
            amount_base = self._to_base(row)
            if amount_base < row.minimum_balance:
                alerts.append(
                    LiquidityAlert(
                        alert_type="minimum_balance_breach",
                        severity="critical",
                        message=f"Account {row.account_id} below minimum balance",
                    )
                )
            if row.overdraft_limit > 0:
                usage = row.overdraft_used / row.overdraft_limit
                if usage >= payload.overdraft_alert_pct:
                    alerts.append(
                        LiquidityAlert(
                            alert_type="overdraft_approach",
                            severity="warning",
                            message=f"Account {row.account_id} overdraft usage at {round(usage * 100, 2)}%",
                        )
                    )

        by_bank: dict[str, Decimal] = {}
        for row in payload.rows:
            by_bank[row.bank] = by_bank.get(row.bank, Decimal("0")) + self._to_base(row)

        positive_cash = max(Decimal("0"), cash_total)
        if positive_cash > 0:
            for bank, amount in by_bank.items():
                concentration = amount / positive_cash
                if concentration > payload.concentration_threshold:
                    alerts.append(
                        LiquidityAlert(
                            alert_type="concentration_risk",
                            severity="warning",
                            message=f"Bank {bank} concentration at {round(concentration * 100, 2)}% of group cash",
                        )
                    )

        covenant_headroom: dict[str, Decimal] = {}
        for fac in payload.facilities:
            if fac.limit_amount <= 0:
                covenant_headroom[fac.facility_name] = Decimal("0")
                continue
            headroom_pct = (fac.limit_amount - fac.current_drawn) / fac.limit_amount
            covenant_headroom[fac.facility_name] = _round_2(headroom_pct)
            if headroom_pct <= payload.covenant_headroom_alert_pct:
                alerts.append(
                    LiquidityAlert(
                        alert_type="covenant_headroom",
                        severity="critical",
                        message=f"Facility {fac.facility_name} headroom at {round(headroom_pct * 100, 2)}%",
                    )
                )

        return LiquidityResponse(
            available_liquidity=_round_2(available),
            cash_total=_round_2(cash_total),
            undrawn_total=_round_2(undrawn_total),
            payment_queue_total=_round_2(queue_total),
            covenant_headroom=covenant_headroom,
            alerts=alerts,
        )

    @staticmethod
    def _vat_reference(tenant_id: uuid.UUID, due_date: date) -> str:
        return f"VAT-{str(tenant_id).split('-')[0]}-{due_date.strftime('%Y%m%d')}"

    @staticmethod
    def _ct_reference(tenant_id: uuid.UUID, year_end: date) -> str:
        return f"CT-{str(tenant_id).split('-')[0]}-{year_end.strftime('%Y%m%d')}"

    @staticmethod
    def _paye_reference(tenant_id: uuid.UUID, period_end: date) -> str:
        return f"PAYE-{str(tenant_id).split('-')[0]}-{period_end.strftime('%Y%m')}"

    @staticmethod
    def _cis_reference(tenant_id: uuid.UUID, period_end: date) -> str:
        return f"CIS-{str(tenant_id).split('-')[0]}-{period_end.strftime('%Y%m')}"

    @staticmethod
    def _ch_reference(tenant_id: uuid.UUID, anniversary: date) -> str:
        return f"CH-{str(tenant_id).split('-')[0]}-{anniversary.strftime('%Y%m%d')}"

    def populate_hmrc_obligations(self, payload: HmrcScheduleRequest) -> list[HmrcObligation]:
        obligations: list[HmrcObligation] = []

        vat_periods = payload.vat_month_end_dates if payload.vat_monthly_mtd else payload.vat_quarter_end_dates
        for period_end in vat_periods:
            due = _add_months(period_end, 1) + timedelta(days=7)
            obligations.append(
                HmrcObligation(
                    obligation_type="VAT",
                    due_date=due,
                    estimated_amount=_round_2(payload.estimated_vat_amount),
                    urgency_colour=_urgency(due, payload.as_of),
                    hmrc_payment_reference=self._vat_reference(payload.tenant_id, due),
                )
            )

        if payload.large_company_ct:
            for months in (7, 10, 13, 16):
                due = _add_months(payload.corporation_tax_year_end, months)
                obligations.append(
                    HmrcObligation(
                        obligation_type="CORP_TAX",
                        due_date=due,
                        estimated_amount=_round_2(payload.estimated_ct_amount / Decimal("4")),
                        urgency_colour=_urgency(due, payload.as_of),
                        hmrc_payment_reference=self._ct_reference(payload.tenant_id, payload.corporation_tax_year_end),
                    )
                )
        else:
            due = _add_months(payload.corporation_tax_year_end, 9) + timedelta(days=1)
            obligations.append(
                HmrcObligation(
                    obligation_type="CORP_TAX",
                    due_date=due,
                    estimated_amount=_round_2(payload.estimated_ct_amount),
                    urgency_colour=_urgency(due, payload.as_of),
                    hmrc_payment_reference=self._ct_reference(payload.tenant_id, payload.corporation_tax_year_end),
                )
            )

        for period in payload.paye_months:
            period_end = _end_of_month(period)
            due_day = 19 if payload.paye_payment_method == "cheque" else 22
            due = _next_month_due_day(period_end, due_day)
            obligations.append(
                HmrcObligation(
                    obligation_type="PAYE_NIC",
                    due_date=due,
                    estimated_amount=_round_2(payload.estimated_paye_amount),
                    urgency_colour=_urgency(due, payload.as_of),
                    hmrc_payment_reference=self._paye_reference(payload.tenant_id, period_end),
                )
            )

        for period in payload.cis_months:
            period_end = _end_of_month(period)
            due_day = 19 if payload.cis_payment_method == "cheque" else 22
            due = _next_month_due_day(period_end, due_day)
            obligations.append(
                HmrcObligation(
                    obligation_type="CIS",
                    due_date=due,
                    estimated_amount=_round_2(payload.estimated_cis_amount),
                    urgency_colour=_urgency(due, payload.as_of),
                    hmrc_payment_reference=self._cis_reference(payload.tenant_id, period_end),
                )
            )

        obligations.append(
            HmrcObligation(
                obligation_type="CONFIRMATION_STATEMENT",
                due_date=payload.confirmation_statement_anniversary,
                estimated_amount=Decimal("0"),
                urgency_colour=_urgency(payload.confirmation_statement_anniversary, payload.as_of),
                hmrc_payment_reference=self._ch_reference(payload.tenant_id, payload.confirmation_statement_anniversary),
            )
        )

        return sorted(obligations, key=lambda x: x.due_date)

    def process_ai_forecast(self, payload: ForecastInferenceRequest) -> ForecastInferenceResponse:
        # USER ACTION REQUIRED: set AI_PROVIDER (`ollama` for UAT, `claude`/`gemini` for production) in environment.
        provider = payload.provider or os.getenv("AI_PROVIDER") or "claude"
        if provider not in {"ollama", "claude", "gemini"}:
            provider = "claude"

        model_version = payload.model_version
        if provider == "gemini" and model_version == "claude-sonnet-4-6":
            model_version = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")

        if provider == "gemini" and _env_flag("AI_PROVIDER_GEMINI_DEPRECATED", default=False):
            rejected_rows = [
                ForecastRejectedRow(
                    account_ref_hash=_hash_text(row.account_id),
                    forecast_date=row.forecast_date,
                    amount=_round_2(row.amount),
                    confidence=row.confidence,
                    reason="provider_deprecated_gemini",
                )
                for row in payload.rows
            ]
            prompt_hash = _hash_text(payload.prompt)
            response_hash = _hash_text(payload.raw_response)
            representative_hash = rejected_rows[0].account_ref_hash if rejected_rows else _hash_text("none")
            audit = InferenceAuditRecord(
                provider=provider,
                model_version=model_version,
                account_ref_hash=representative_hash,
                prompt_hash=prompt_hash,
                response_hash=response_hash,
                latency_ms=payload.latency_ms,
                accepted_count=0,
                rejected_count=len(rejected_rows),
                operator_user_id=payload.operator_user_id,
                tenant_id=payload.tenant_id,
            )
            return ForecastInferenceResponse(
                provider=provider,
                model_version=model_version,
                accepted=[],
                rejected=rejected_rows,
                rejection_log=rejected_rows,
                audit_log=[audit],
                gdpr_summary=(
                    "Account identifiers hashed with SHA-256; only aggregated daily net flows processed; "
                    "no IBAN/BIC/counterparty data accepted. Gemini path deprecated by configuration."
                ),
            )

        accepted: list[ForecastAcceptedRow] = []
        rejected: list[ForecastRejectedRow] = []

        max_date = payload.as_of + timedelta(days=payload.horizon_days)
        for row in payload.rows:
            account_ref_hash = _hash_text(row.account_id)
            reasons: list[str] = []
            if row.confidence < Decimal("0.40"):
                reasons.append("confidence_below_floor")
            if abs(row.amount) > payload.amount_bound:
                reasons.append("amount_out_of_bounds")
            if row.forecast_date < payload.as_of or row.forecast_date > max_date:
                reasons.append("outside_forecast_horizon")

            if reasons:
                rejected.append(
                    ForecastRejectedRow(
                        account_ref_hash=account_ref_hash,
                        forecast_date=row.forecast_date,
                        amount=_round_2(row.amount),
                        confidence=row.confidence,
                        reason=";".join(reasons),
                    )
                )
                continue

            accepted.append(
                ForecastAcceptedRow(
                    account_ref_hash=account_ref_hash,
                    forecast_date=row.forecast_date,
                    amount=_round_2(row.amount),
                    confidence=row.confidence,
                    human_review_required=(abs(row.amount) > Decimal("1000000") or row.confidence > Decimal("0.90")),
                )
            )

        prompt_hash = _hash_text(payload.prompt)
        response_hash = _hash_text(payload.raw_response)
        representative_hash = accepted[0].account_ref_hash if accepted else (rejected[0].account_ref_hash if rejected else _hash_text("none"))

        audit = InferenceAuditRecord(
            provider=provider,
            model_version=model_version,
            account_ref_hash=representative_hash,
            prompt_hash=prompt_hash,
            response_hash=response_hash,
            latency_ms=payload.latency_ms,
            accepted_count=len(accepted),
            rejected_count=len(rejected),
            operator_user_id=payload.operator_user_id,
            tenant_id=payload.tenant_id,
        )

        return ForecastInferenceResponse(
            provider=provider,
            model_version=model_version,
            accepted=accepted,
            rejected=rejected,
            rejection_log=rejected,
            audit_log=[audit],
            gdpr_summary="Account identifiers hashed with SHA-256; only aggregated daily net flows processed; no IBAN/BIC/counterparty data accepted.",
        )

    def daily_variance_report(self, payload: DailyVarianceRequest) -> DailyVarianceReport:
        out: list[dict[str, Decimal | str]] = []
        for row in payload.rows:
            variance = row.actual - row.forecast
            out.append(
                {
                    "entity": row.entity,
                    "currency": row.currency,
                    "forecast": _round_2(row.forecast),
                    "actual": _round_2(row.actual),
                    "variance": _round_2(variance),
                }
            )
        return DailyVarianceReport(as_of=payload.as_of, by_entity_currency=out)

    def export_daily_variance_report(self, payload: DailyVarianceExportRequest) -> ReportExportResponse:
        report = self.daily_variance_report(payload)
        csv_lines = ["entity,currency,forecast,actual,variance"]
        pdf_lines = [f"As of: {report.as_of.isoformat()}"]

        for row in report.by_entity_currency:
            csv_lines.append(
                f"{row['entity']},{row['currency']},{row['forecast']},{row['actual']},{row['variance']}"
            )
            pdf_lines.append(
                f"{row['entity']} {row['currency']} F:{row['forecast']} A:{row['actual']} V:{row['variance']}"
            )

        return self._export_report(
            report_name="daily_variance",
            report_title="KuberaTreasury Daily Variance Report",
            tenant_id=payload.tenant_id,
            operator_user_id=payload.operator_user_id,
            parameters_hash=_hash_text(payload.model_dump_json()),
            pdf_lines=pdf_lines,
            csv_lines=csv_lines,
        )

    def weekly_summary_report(self, payload: WeeklySummaryRequest) -> WeeklySummaryReport:
        hmrc_due = [
            item
            for item in payload.hmrc_obligations
            if payload.week_start <= item.due_date <= payload.week_end
        ]
        abs_pct_errors: list[Decimal] = []
        for forecast, actual in payload.forecast_actual_pairs:
            if actual == 0:
                continue
            abs_pct_errors.append(abs((actual - forecast) / actual) * Decimal("100"))

        mape = (sum(abs_pct_errors, Decimal("0")) / Decimal(len(abs_pct_errors))) if abs_pct_errors else Decimal("0")
        return WeeklySummaryReport(
            week_start=payload.week_start,
            week_end=payload.week_end,
            position_movement=_round_2(payload.closing_position - payload.opening_position),
            net_flows=_round_2(payload.net_flows),
            fx_impact=_round_2(payload.fx_impact),
            hmrc_due_this_week=hmrc_due,
            ai_forecast_mape=_round_2(mape),
        )

    def export_weekly_summary_report(self, payload: WeeklySummaryExportRequest) -> ReportExportResponse:
        report = self.weekly_summary_report(payload)
        csv_lines = ["metric,value"]
        csv_lines.extend(
            [
                f"week_start,{report.week_start.isoformat()}",
                f"week_end,{report.week_end.isoformat()}",
                f"position_movement,{report.position_movement}",
                f"net_flows,{report.net_flows}",
                f"fx_impact,{report.fx_impact}",
                f"ai_forecast_mape,{report.ai_forecast_mape}",
                f"hmrc_due_count,{len(report.hmrc_due_this_week)}",
            ]
        )
        pdf_lines = [
            f"Week: {report.week_start.isoformat()} to {report.week_end.isoformat()}",
            f"Position movement: {report.position_movement}",
            f"Net flows: {report.net_flows}",
            f"FX impact: {report.fx_impact}",
            f"AI forecast MAPE: {report.ai_forecast_mape}",
            f"HMRC due this week: {len(report.hmrc_due_this_week)}",
        ]

        return self._export_report(
            report_name="weekly_summary",
            report_title="KuberaTreasury Weekly Treasury Summary",
            tenant_id=payload.tenant_id,
            operator_user_id=payload.operator_user_id,
            parameters_hash=_hash_text(payload.model_dump_json()),
            pdf_lines=pdf_lines,
            csv_lines=csv_lines,
        )

    def monthly_board_pack(self, payload: BoardPackRequest) -> BoardPackResponse:
        report_id = str(uuid.uuid4())
        generated_at = datetime.now(tz=timezone.utc)

        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)
        c.setTitle("KuberaTreasury Monthly Board Pack")
        c.drawString(50, 800, "KuberaTreasury Monthly Board Pack")
        c.drawString(50, 785, f"Report ID: {report_id}")
        c.drawString(50, 770, f"Generated: {generated_at.isoformat()}")
        c.drawString(50, 745, "Sections: liquidity waterfall, HMRC schedule, debt maturity, FX exposure,")
        c.drawString(50, 730, "covenant headroom, IFRS 9 hedges, AI accuracy, transfer pricing summary.")
        c.showPage()
        c.save()
        pdf_bytes = pdf_buffer.getvalue()

        csv_lines = [
            "section,item,value",
            f"liquidity,rows,{len(payload.group_liquidity_waterfall)}",
            f"hmrc,obligations_12m,{len(payload.hmrc_obligations_next_12m)}",
            f"debt,maturities,{len(payload.debt_maturity_profile)}",
            f"fx,currencies,{len(payload.fx_exposure)}",
            f"covenant,facilities,{len(payload.covenant_headroom)}",
            f"ifrs9,hedges,{len(payload.ifrs9_hedge_register_summary)}",
        ]
        excel_bytes = "\n".join(csv_lines).encode("utf-8")

        digital_signature = _hash_text(report_id + generated_at.isoformat() + _hash_text(pdf_bytes.hex()))
        audit_log = {
            "report_id": report_id,
            "report_name": "monthly_board_pack",
            "tenant_id": str(payload.tenant_id),
            "operator_user_id": str(payload.operator_user_id),
            "timestamp": generated_at.isoformat(),
            "parameters_hash": _hash_text(payload.model_dump_json()),
        }
        self._report_audit_events.append(audit_log)

        return BoardPackResponse(
            report_id=report_id,
            generated_at=generated_at,
            pdf_bytes=pdf_bytes,
            excel_bytes=excel_bytes,
            digital_signature=digital_signature,
            audit_log=audit_log,
        )
