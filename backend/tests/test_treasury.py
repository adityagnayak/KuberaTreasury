from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.treasury_service import (
    BoardPackRequest,
    DailyVarianceRequest,
    FacilityRow,
    ForecastInferenceRequest,
    ForecastRowInput,
    HmrcScheduleRequest,
    LiquidityRequest,
    PaymentQueueItem,
    PositionRequest,
    PositionRow,
    SweepSimulationRequest,
    TreasuryService,
    VarianceRow,
    WeeklySummaryRequest,
)


def test_consolidated_position_and_buckets() -> None:
    svc = TreasuryService()
    res = svc.consolidated_position(
        PositionRequest(
            rows=[
                PositionRow(entity="UK", bank="BankA", account_id="A1", currency="GBP", balance=Decimal("100"), maturity_days=0),
                PositionRow(entity="UK", bank="BankB", account_id="A2", currency="USD", balance=Decimal("50"), fx_to_base=Decimal("0.8"), maturity_days=10),
            ]
        )
    )
    assert res.consolidated_group_position == Decimal("140.00")
    assert res.maturity_buckets["same_day"] == Decimal("100.00")
    assert res.maturity_buckets["d8_30"] == Decimal("40.00")


def test_intraday_sweep_simulation() -> None:
    svc = TreasuryService()
    res = svc.simulate_intraday_sweep(
        SweepSimulationRequest(
            rows=[PositionRow(entity="UK", bank="BankA", account_id="A1", currency="GBP", balance=Decimal("200"))],
            proposed_payments=[PaymentQueueItem(account_id="A1", amount_base=Decimal("30"))],
        )
    )
    assert res.before_position == Decimal("200.00")
    assert res.after_position == Decimal("170.00")
    assert res.by_account_after["A1"] == Decimal("170.00")


def test_available_liquidity_and_alerts() -> None:
    svc = TreasuryService()
    res = svc.available_liquidity_and_alerts(
        LiquidityRequest(
            rows=[
                PositionRow(
                    entity="UK",
                    bank="BankA",
                    account_id="A1",
                    currency="GBP",
                    balance=Decimal("80"),
                    minimum_balance=Decimal("100"),
                    overdraft_limit=Decimal("100"),
                    overdraft_used=Decimal("85"),
                ),
                PositionRow(entity="US", bank="BankA", account_id="A2", currency="GBP", balance=Decimal("120")),
            ],
            facilities=[FacilityRow(facility_name="RCF", bank="BankA", limit_amount=Decimal("1000"), current_drawn=Decimal("950"))],
            payment_queue=[PaymentQueueItem(account_id="A1", amount_base=Decimal("10"))],
        )
    )
    assert res.available_liquidity == Decimal("240.00")
    alert_types = {a.alert_type for a in res.alerts}
    assert "minimum_balance_breach" in alert_types
    assert "overdraft_approach" in alert_types
    assert "concentration_risk" in alert_types
    assert "covenant_headroom" in alert_types


def test_hmrc_obligations_standard_ct_and_vat() -> None:
    svc = TreasuryService()
    tenant_id = uuid.uuid4()
    out = svc.populate_hmrc_obligations(
        HmrcScheduleRequest(
            tenant_id=tenant_id,
            as_of=date(2026, 3, 1),
            vat_quarter_end_dates=[date(2026, 3, 31)],
            corporation_tax_year_end=date(2026, 12, 31),
            large_company_ct=False,
            paye_months=[date(2026, 3, 1)],
            cis_months=[date(2026, 3, 1)],
            confirmation_statement_anniversary=date(2026, 8, 15),
            estimated_vat_amount=Decimal("1200"),
            estimated_ct_amount=Decimal("10000"),
            estimated_paye_amount=Decimal("4000"),
            estimated_cis_amount=Decimal("500"),
        )
    )
    assert any(o.obligation_type == "VAT" for o in out)
    assert any(o.obligation_type == "CORP_TAX" for o in out)
    assert any(o.obligation_type == "PAYE_NIC" for o in out)
    assert any(o.obligation_type == "CIS" for o in out)
    assert any(o.obligation_type == "CONFIRMATION_STATEMENT" for o in out)


def test_ai_forecast_validation_pipeline_and_hashing() -> None:
    svc = TreasuryService()
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    out = svc.process_ai_forecast(
        ForecastInferenceRequest(
            tenant_id=tenant_id,
            operator_user_id=user_id,
            as_of=date(2026, 3, 1),
            horizon_days=30,
            rows=[
                ForecastRowInput(account_id="ACC-1", forecast_date=date(2026, 3, 10), amount=Decimal("1500000"), confidence=Decimal("0.91")),
                ForecastRowInput(account_id="ACC-2", forecast_date=date(2026, 5, 10), amount=Decimal("10"), confidence=Decimal("0.50")),
                ForecastRowInput(account_id="ACC-3", forecast_date=date(2026, 3, 12), amount=Decimal("10"), confidence=Decimal("0.20")),
            ],
            prompt="forecast prompt",
            raw_response="forecast response",
            latency_ms=123,
        )
    )
    assert len(out.accepted) == 1
    assert out.accepted[0].human_review_required is True
    assert len(out.rejected) == 2
    assert out.audit_log[0].provider in {"claude", "ollama"}
    assert len(out.accepted[0].account_ref_hash) == 64


def test_daily_variance_and_weekly_summary() -> None:
    svc = TreasuryService()
    variance = svc.daily_variance_report(
        DailyVarianceRequest(
            as_of=date(2026, 3, 4),
            rows=[VarianceRow(entity="UK", currency="GBP", forecast=Decimal("100"), actual=Decimal("120"))],
        )
    )
    assert variance.by_entity_currency[0]["variance"] == Decimal("20.00")

    weekly = svc.weekly_summary_report(
        WeeklySummaryRequest(
            as_of=date(2026, 3, 4),
            week_start=date(2026, 3, 2),
            week_end=date(2026, 3, 8),
            opening_position=Decimal("1000"),
            closing_position=Decimal("1200"),
            net_flows=Decimal("150"),
            fx_impact=Decimal("20"),
            hmrc_obligations=[],
            forecast_actual_pairs=[(Decimal("100"), Decimal("120")), (Decimal("50"), Decimal("40"))],
        )
    )
    assert weekly.position_movement == Decimal("200.00")
    assert weekly.ai_forecast_mape > 0


def test_monthly_board_pack_returns_signed_payload() -> None:
    svc = TreasuryService()
    out = svc.monthly_board_pack(
        BoardPackRequest(
            tenant_id=uuid.uuid4(),
            operator_user_id=uuid.uuid4(),
            as_of=date(2026, 3, 4),
            group_liquidity_waterfall=[{"day": "D+0", "value": Decimal("1000")}],
            hmrc_obligations_next_12m=[],
            debt_maturity_profile=[],
            fx_exposure=[],
            covenant_headroom=[],
            ifrs9_hedge_register_summary=[],
            ai_forecast_accuracy_metrics={"mape": Decimal("4.2")},
            transfer_pricing_summary={"cir_status": "ok", "interco_volumes": Decimal("100")},
        )
    )
    assert out.report_id
    assert len(out.pdf_bytes) > 0
    assert len(out.excel_bytes) > 0
    assert len(out.digital_signature) == 64


def test_treasury_api_endpoints() -> None:
    app = create_app()
    client = TestClient(app)

    payload = {
        "rows": [
            {
                "entity": "UK",
                "bank": "BankA",
                "account_id": "A1",
                "currency": "GBP",
                "balance": "100",
                "fx_to_base": "1",
                "maturity_days": 0,
                "minimum_balance": "0",
                "overdraft_limit": "0",
                "overdraft_used": "0",
            }
        ]
    }

    resp = client.post("/api/v1/treasury/position", json=payload)
    assert resp.status_code == 200
    assert resp.json()["consolidated_group_position"] == "100.00"

    ai_resp = client.post(
        "/api/v1/treasury/ai/forecast",
        json={
            "tenant_id": str(uuid.uuid4()),
            "operator_user_id": str(uuid.uuid4()),
            "as_of": "2026-03-01",
            "horizon_days": 10,
            "rows": [
                {
                    "account_id": "A1",
                    "forecast_date": "2026-03-03",
                    "amount": "100",
                    "confidence": "0.7",
                }
            ],
            "prompt": "p",
            "raw_response": "r",
            "latency_ms": 50,
        },
    )
    assert ai_resp.status_code == 200
    assert ai_resp.json()["hitl_enforced"] is True
