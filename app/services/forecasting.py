"""
NexusTreasury — Liquidity Forecasting Service (Phase 2)
Forecast ingestion, reconciliation, variance analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.business_days import BusinessDayAdjuster
from app.models.forecasts import ForecastEntry, VarianceAlert
from app.models.transactions import Transaction

getcontext().prec = 28


@dataclass
class ForecastEntryInput:
    account_id: str
    currency: str
    expected_date: date
    forecast_amount: Decimal
    description: Optional[str] = None
    auto_roll_bday: bool = True


@dataclass
class AlertDTO:
    alert_id: str
    alert_type: str
    account_id: str
    forecast_amount: Optional[Decimal]
    actual_amount: Optional[Decimal]
    variance_pct: Optional[Decimal]
    currency: str
    triggered_at: datetime


@dataclass
class ReconciliationReport:
    as_of_date: date
    matched: int
    unmatched_forecasts: int
    unmatched_actuals: int
    partially_matched: int
    high_priority_alerts: List[AlertDTO]


@dataclass
class VarianceReport:
    from_date: date
    to_date: date
    entity_id: Optional[str]
    total_forecast: Decimal
    total_actual: Decimal
    net_variance: Decimal
    variance_pct: Optional[Decimal]
    high_priority_items: List[AlertDTO]
    detail_rows: List[dict]


class LiquidityForecastingService:
    """Ingests forecasts, reconciles against actuals, produces variance reports."""

    PARTIAL_MATCH_THRESHOLD = Decimal("5")  # >5% diff = PARTIALLY_MATCHED

    def __init__(
        self,
        session: Session,
        variance_threshold_pct: Decimal = Decimal("500"),
    ) -> None:
        self._session = session
        self._variance_threshold = variance_threshold_pct

    # ── Ingest ────────────────────────────────────────────────────────────────

    def ingest_forecast(self, entries: List[ForecastEntryInput]) -> None:
        for e in entries:
            if not isinstance(e.forecast_amount, Decimal):
                raise TypeError(
                    f"forecast_amount must be Decimal, got {type(e.forecast_amount)}"
                )

            row = ForecastEntry(
                account_id=e.account_id,
                currency=e.currency,
                expected_date=e.expected_date,
                forecast_amount=e.forecast_amount,
                description=e.description,
            )
            self._session.add(row)
            self._session.flush()

            if e.auto_roll_bday:
                try:
                    adjuster = BusinessDayAdjuster(e.currency, "modified_following")
                    adjusted = adjuster.adjust(row.expected_date)
                    if adjusted != row.expected_date:
                        row.original_expected_date = row.expected_date
                        row.expected_date = adjusted
                        row.updated_at = datetime.utcnow()
                        self._session.flush()
                except ValueError:
                    pass  # No country mapping — skip roll

        self._session.commit()

    # ── Reconcile ─────────────────────────────────────────────────────────────

    def reconcile_actuals(self, as_of_date: date) -> ReconciliationReport:
        window_start = as_of_date - timedelta(days=3)
        window_end = as_of_date + timedelta(days=3)

        forecasts = (
            self._session.query(ForecastEntry)
            .filter(
                ForecastEntry.expected_date.between(window_start, window_end),
                ForecastEntry.reconciliation_status == "PENDING",
            )
            .all()
        )

        actuals = (
            self._session.query(Transaction)
            .filter(
                Transaction.value_date.between(window_start, window_end),
                Transaction.status == "booked",
            )
            .all()
        )

        actual_index: Dict[Tuple, List[Transaction]] = {}
        for txn in actuals:
            key = (txn.account_id, txn.currency, txn.value_date)
            actual_index.setdefault(key, []).append(txn)

        matched_txn_ids: set = set()
        high_priority: List[AlertDTO] = []
        counts = {
            "MATCHED": 0,
            "UNMATCHED_FORECAST": 0,
            "UNMATCHED_ACTUAL": 0,
            "PARTIALLY_MATCHED": 0,
        }

        for fc in forecasts:
            fc_amount = Decimal(str(fc.forecast_amount))
            candidates = self._find_matching_actuals(fc, actual_index)

            if not candidates:
                fc.reconciliation_status = "UNMATCHED_FORECAST"
                counts["UNMATCHED_FORECAST"] += 1
                continue

            best_txn = min(
                candidates,
                key=lambda t: abs(Decimal(str(t.amount)) - abs(fc_amount)),
            )
            actual_amount = Decimal(str(best_txn.amount))
            amount_diff_pct = (
                abs(actual_amount - abs(fc_amount)) / abs(fc_amount) * Decimal("100")
                if fc_amount != Decimal("0")
                else Decimal("100")
            )

            if amount_diff_pct <= self.PARTIAL_MATCH_THRESHOLD:
                fc.reconciliation_status = "MATCHED"
                counts["MATCHED"] += 1
            else:
                fc.reconciliation_status = "PARTIALLY_MATCHED"
                counts["PARTIALLY_MATCHED"] += 1

            fc.matched_transaction_id = best_txn.id
            fc.updated_at = datetime.utcnow()
            matched_txn_ids.add(best_txn.id)

            alert = self._check_variance(fc, best_txn)
            if alert:
                high_priority.append(alert)

        counts["UNMATCHED_ACTUAL"] = sum(
            1 for txn in actuals if txn.id not in matched_txn_ids
        )
        self._session.commit()

        return ReconciliationReport(
            as_of_date=as_of_date,
            matched=counts["MATCHED"],
            unmatched_forecasts=counts["UNMATCHED_FORECAST"],
            unmatched_actuals=counts["UNMATCHED_ACTUAL"],
            partially_matched=counts["PARTIALLY_MATCHED"],
            high_priority_alerts=high_priority,
        )

    def _find_matching_actuals(
        self,
        fc: ForecastEntry,
        actual_index: Dict[Tuple, List[Transaction]],
    ) -> List[Transaction]:
        results = []
        for delta in (-1, 0, 1):
            key = (fc.account_id, fc.currency, fc.expected_date + timedelta(days=delta))
            results.extend(actual_index.get(key, []))
        return results

    def _check_variance(
        self, fc: ForecastEntry, actual_txn: Transaction
    ) -> Optional[AlertDTO]:
        forecast_amt = Decimal(str(fc.forecast_amount))
        actual_amt = Decimal(str(actual_txn.amount))
        if actual_txn.credit_debit_indicator == "DBIT":
            actual_amt = -actual_amt

        if forecast_amt == Decimal("0"):
            variance_pct = None
            is_high = actual_amt != Decimal("0")
        else:
            variance_pct = (
                abs(actual_amt - forecast_amt) / abs(forecast_amt) * Decimal("100")
            )
            is_high = variance_pct > self._variance_threshold

        if not is_high:
            return None

        alert_row = VarianceAlert(
            alert_type="HIGH_PRIORITY_INVESTIGATION",
            account_id=fc.account_id,
            forecast_id=fc.id,
            transaction_id=actual_txn.id,
            forecast_amount=forecast_amt,
            actual_amount=actual_amt,
            variance_pct=variance_pct,
            currency=fc.currency,
            notes=(
                "Infinite variance (forecast=0)"
                if variance_pct is None
                else f"Variance {variance_pct:.2f}% exceeds threshold {self._variance_threshold}%"
            ),
        )
        self._session.add(alert_row)
        self._session.flush()

        return AlertDTO(
            alert_id=alert_row.id,
            alert_type=alert_row.alert_type,
            account_id=alert_row.account_id,
            forecast_amount=forecast_amt,
            actual_amount=actual_amt,
            variance_pct=variance_pct,
            currency=fc.currency,
            triggered_at=alert_row.triggered_at,
        )

    # ── Variance Report ───────────────────────────────────────────────────────

    def get_variance_report(
        self,
        from_date: date,
        to_date: date,
        entity_id: Optional[str] = None,
    ) -> VarianceReport:
        from app.models.entities import BankAccount

        query = self._session.query(ForecastEntry).filter(
            ForecastEntry.expected_date.between(from_date, to_date),
            ForecastEntry.reconciliation_status != "PENDING",
        )

        if entity_id:
            account_ids = [
                a.id
                for a in self._session.query(BankAccount)
                .filter_by(entity_id=entity_id)
                .all()
            ]
            query = query.filter(ForecastEntry.account_id.in_(account_ids))

        forecasts = query.all()

        total_forecast = Decimal("0")
        total_actual = Decimal("0")
        detail_rows = []
        high_priority: List[AlertDTO] = []

        for fc in forecasts:
            fc_amount = Decimal(str(fc.forecast_amount))
            total_forecast += fc_amount
            actual_amount: Optional[Decimal] = None

            if fc.matched_transaction_id:
                txn = (
                    self._session.query(Transaction)
                    .filter_by(id=fc.matched_transaction_id)
                    .first()
                )
                if txn:
                    actual_amount = Decimal(str(txn.amount))
                    if txn.credit_debit_indicator == "DBIT":
                        actual_amount = -actual_amount
                    total_actual += actual_amount

            alerts = (
                self._session.query(VarianceAlert)
                .filter_by(forecast_id=fc.id, alert_type="HIGH_PRIORITY_INVESTIGATION")
                .all()
            )
            for a in alerts:
                high_priority.append(
                    AlertDTO(
                        alert_id=a.id,
                        alert_type=a.alert_type,
                        account_id=a.account_id,
                        forecast_amount=Decimal(str(a.forecast_amount))
                        if a.forecast_amount
                        else None,
                        actual_amount=Decimal(str(a.actual_amount))
                        if a.actual_amount
                        else None,
                        variance_pct=Decimal(str(a.variance_pct))
                        if a.variance_pct
                        else None,
                        currency=a.currency or fc.currency,
                        triggered_at=a.triggered_at,
                    )
                )

            detail_rows.append(
                {
                    "forecast_id": fc.id,
                    "account_id": fc.account_id,
                    "currency": fc.currency,
                    "expected_date": fc.expected_date,
                    "forecast_amount": fc_amount,
                    "actual_amount": actual_amount,
                    "status": fc.reconciliation_status,
                    "has_alert": len(alerts) > 0,
                }
            )

        net_variance = total_actual - total_forecast
        variance_pct = (
            abs(net_variance) / abs(total_forecast) * Decimal("100")
            if total_forecast != Decimal("0")
            else None
        )

        return VarianceReport(
            from_date=from_date,
            to_date=to_date,
            entity_id=entity_id,
            total_forecast=total_forecast,
            total_actual=total_actual,
            net_variance=net_variance,
            variance_pct=variance_pct,
            high_priority_items=high_priority,
            detail_rows=detail_rows,
        )
