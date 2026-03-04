from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.payments_compliance_service import (
    ApprovalDecisionIn,
    HmrcMtdService,
    MtdVatReturnBuildRequest,
    Pain001BatchRequest,
    PaymentInstructionIn,
    PaymentsComplianceService,
    RegulatoryExportRequest,
    RegulatoryExportService,
    SignatureVerificationRequest,
)


def _payment_payload(**overrides):
    base = PaymentInstructionIn(
        tenant_id=uuid.uuid4(),
        initiator_user_id=uuid.uuid4(),
        initiator_role="treasury_analyst",
        debit_bank_account_id=uuid.uuid4(),
        counterparty_id=uuid.uuid4(),
        beneficiary_name="Acme Supplies Ltd",
        amount=Decimal("5000"),
        currency_code="GBP",
        scheduled_for=datetime.now(tz=timezone.utc) + timedelta(hours=2),
        urgent=False,
        same_day=False,
        available_balance=Decimal("100000"),
        overdraft_limit=Decimal("10000"),
        min_buffer=Decimal("1000"),
        destination_country_code="GB",
        ip_address="10.0.0.1",
        registered_company_name="Acme Supplies Ltd",
        vat_number="123456789",
    )
    return base.model_copy(update=overrides)


def test_approval_matrix_defaults_and_currency_urgent_rules() -> None:
    svc = PaymentsComplianceService()
    payload = _payment_payload(currency_code="USD", urgent=True, same_day=True)
    out = svc.initiate_payment(payload)
    assert "treasury_manager" in out.required_approver_roles
    assert "head_of_treasury" in out.required_approver_roles
    assert "cfo" in out.required_approver_roles
    assert out.enhanced_due_diligence_required is True


def test_hmrc_reference_formats_enforced() -> None:
    svc = PaymentsComplianceService()
    with pytest.raises(ValueError):
        svc.initiate_payment(_payment_payload(hmrc_tax_type="CT", hmrc_payment_reference="123"))

    out = svc.initiate_payment(_payment_payload(hmrc_tax_type="CT", hmrc_payment_reference="1234567890A001"))
    assert out.status == "PENDING_APPROVAL"


def test_funds_check_and_duplicate_detection() -> None:
    svc = PaymentsComplianceService()
    with pytest.raises(ValueError):
        svc.initiate_payment(_payment_payload(available_balance=Decimal("100"), overdraft_limit=Decimal("0"), min_buffer=Decimal("50")))

    p1 = _payment_payload()
    out1 = svc.initiate_payment(p1)
    assert out1.duplicate_detected is False

    p2 = p1.model_copy(update={"initiator_user_id": uuid.uuid4()})
    out2 = svc.initiate_payment(p2)
    assert out2.duplicate_detected is True


def test_mandate_checks_block_on_mismatch() -> None:
    svc = PaymentsComplianceService()
    out = svc.initiate_payment(
        _payment_payload(
            beneficiary_name="Totally Different Name",
            registered_company_name="Acme Supplies Ltd",
            vat_number="123456789",
        )
    )
    assert out.status == "REJECTED"
    assert out.compliance_alerted is True


def test_sanctions_match_freezes_and_logs() -> None:
    svc = PaymentsComplianceService()
    out = svc.initiate_payment(
        _payment_payload(
            beneficiary_name="Bank Melli Iran",
            registered_company_name="Bank Melli Iran",
            destination_country_code="IR",
        )
    )
    assert out.frozen is True
    assert out.under_review is True
    assert out.sanctions_match_score >= Decimal("85")


def test_four_eyes_initiator_cannot_approve() -> None:
    svc = PaymentsComplianceService()
    p = _payment_payload()
    out = svc.initiate_payment(p)

    with pytest.raises(ValueError):
        svc.approve_payment(
            ApprovalDecisionIn(
                payment_id=out.payment_id,
                approver_user_id=p.initiator_user_id,
                approver_role="treasury_manager",
                decision="approved",
            )
        )


def test_approval_and_state_progression_to_reconciled() -> None:
    svc = PaymentsComplianceService()
    out = svc.initiate_payment(_payment_payload())

    partially = svc.approve_payment(
        ApprovalDecisionIn(
            payment_id=out.payment_id,
            approver_user_id=uuid.uuid4(),
            approver_role="treasury_manager",
            decision="approved",
        )
    )
    assert partially.status == "PENDING_APPROVAL"

    approved = svc.approve_payment(
        ApprovalDecisionIn(
            payment_id=out.payment_id,
            approver_user_id=uuid.uuid4(),
            approver_role="compliance_officer",
            decision="approved",
        )
    )
    assert approved.status == "APPROVED"

    batch = svc.export_pain001_batch(
        Pain001BatchRequest(
            tenant_id=approved.tenant_id,
            batch_id=uuid.uuid4(),
            debtor_name="Kubera Treasury",
            debtor_iban="GB12BARC20201512345678",
            debtor_bic="BARCGB22",
            payment_ids=[approved.payment_id],
            requested_by_user_id=uuid.uuid4(),
        )
    )
    assert batch.xml_content.startswith("<?xml")

    confirmed = svc.confirm_payment(approved.payment_id, actor_user_id=uuid.uuid4())
    assert confirmed.status == "CONFIRMED"

    reconciled = svc.reconcile_payment(approved.payment_id, actor_user_id=uuid.uuid4())
    assert reconciled.status == "RECONCILED"


def test_sar_tipping_off_prevention_view() -> None:
    svc = PaymentsComplianceService()
    out = svc.initiate_payment(
        _payment_payload(
            beneficiary_name="National Iranian Oil Company",
            registered_company_name="National Iranian Oil Company",
            destination_country_code="IR",
            amount=Decimal("60000"),
            initiator_role="treasury_manager",
        )
    )
    public_view = svc.sar_case_view(out.payment_id, requester_role="treasury_manager")
    assert public_view["status"] == "under review"


def test_mlro_clear_and_report_paths() -> None:
    svc = PaymentsComplianceService()
    out = svc.initiate_payment(
        _payment_payload(
            beneficiary_name="National Iranian Oil Company",
            registered_company_name="National Iranian Oil Company",
            destination_country_code="IR",
        )
    )
    cleared = svc.mlro_decision(out.payment_id, mlro_user_id=uuid.uuid4(), decision="CLEAR")
    assert cleared.under_review is False

    out2 = svc.initiate_payment(
        _payment_payload(
            counterparty_id=uuid.uuid4(),
            beneficiary_name="Bank Melli Iran",
            registered_company_name="Bank Melli Iran",
            destination_country_code="IR",
        )
    )
    reported = svc.mlro_decision(out2.payment_id, mlro_user_id=uuid.uuid4(), decision="REPORT")
    assert reported.under_review is True


def test_hmrc_vat_return_builder() -> None:
    svc = HmrcMtdService()
    res = svc.build_vat_return(
        MtdVatReturnBuildRequest(
            tenant_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            period_key="24A1",
            rows=[
                {"vat_treatment": "T1", "net_amount": Decimal("1000"), "vat_amount": Decimal("200")},
                {"vat_treatment": "T0", "net_amount": Decimal("500"), "vat_amount": Decimal("0")},
                {"vat_treatment": "T1", "net_amount": Decimal("-200"), "vat_amount": Decimal("-40")},
            ],
        )
    )
    assert res.box_1 == Decimal("200.00")
    assert res.box_4 == Decimal("40.00")
    assert res.box_6 == Decimal("1500.00")


def test_hmrc_sandbox_endpoint_and_audit_log(monkeypatch) -> None:
    called = {"url": ""}

    class _Resp:
        status_code = 200
        headers = {"CorrelationId": "corr-123"}
        content = b"{}"

        def json(self):
            return {"ok": True}

    def fake_request(self, method, url, json=None, headers=None):
        called["url"] = url
        return _Resp()

    monkeypatch.setenv("HMRC_SANDBOX_MODE", "true")
    monkeypatch.setenv("HMRC_TOKEN_ENCRYPTION_KEY", "a" * 64)
    monkeypatch.setattr(httpx.Client, "request", fake_request)

    svc = HmrcMtdService()
    svc.store_oauth_tokens(uuid.uuid4(), "access", "refresh")
    out = svc.obligations(tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), vrn="123456789")
    assert out["ok"] is True
    assert "test-api.service.hmrc.gov.uk" in called["url"]
    assert len(svc.audit_log()) == 1


def test_regulatory_export_bundle_and_signature_verification() -> None:
    svc = RegulatoryExportService()
    tenant_id = uuid.uuid4()
    bundle = svc.generate_bundle(
        RegulatoryExportRequest(
            tenant_id=tenant_id,
            operator_user_id=uuid.uuid4(),
            from_ts=datetime.now(tz=timezone.utc) - timedelta(days=7),
            to_ts=datetime.now(tz=timezone.utc),
            journal_entries=[{"id": "j1"}],
            payment_audit_trail=[{"id": "p1"}],
            user_activity=[{"id": "u1"}],
            ai_inference_log=[{"id": "a1"}],
            include_sar_activity=False,
            requester_role="auditor",
        )
    )
    assert len(bundle.pdf_bytes) > 0
    assert len(bundle.excel_bytes) > 0
    assert len(bundle.json_bytes) > 0
    check = svc.verify_signature(
        SignatureVerificationRequest(
            tenant_id=tenant_id,
            pdf_bytes=bundle.pdf_bytes,
            generated_at=bundle.generated_at,
            signature=bundle.digital_signature,
        )
    )
    assert check.valid is True


def test_retention_alerts_year_6_and_due() -> None:
    svc = RegulatoryExportService()
    alerts = svc.retention_alerts(
        [
            {"record_id": "r1", "created_date": "2019-01-01", "retention_years": "7"},
            {"record_id": "r2", "created_date": "2014-01-01", "retention_years": "10"},
        ]
    )
    actions = {f"{a['record_id']}:{a['action']}" for a in alerts}
    assert "r1:review_at_year_6" in actions
    assert "r2:retention_due" in actions


def test_payments_api_smoke() -> None:
    app = create_app()
    client = TestClient(app)

    initiate = client.post(
        "/api/v1/payments/initiate",
        json={
            "tenant_id": str(uuid.uuid4()),
            "initiator_user_id": str(uuid.uuid4()),
            "initiator_role": "treasury_analyst",
            "debit_bank_account_id": str(uuid.uuid4()),
            "counterparty_id": str(uuid.uuid4()),
            "beneficiary_name": "Acme Supplies Ltd",
            "amount": "5000",
            "currency_code": "GBP",
            "scheduled_for": (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat(),
            "urgent": False,
            "same_day": False,
            "available_balance": "100000",
            "overdraft_limit": "10000",
            "min_buffer": "1000",
            "destination_country_code": "GB",
            "ip_address": "10.0.0.1",
            "registered_company_name": "Acme Supplies Ltd",
            "vat_number": "123456789",
        },
    )
    assert initiate.status_code == 200
    assert initiate.json()["status"] in {"PENDING_APPROVAL", "REJECTED"}
