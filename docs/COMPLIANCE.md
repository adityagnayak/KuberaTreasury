# COMPLIANCE

## HMRC Regulation Mapping

- MTD obligations/submissions scheduling
  - Implementation: `backend/app/services/treasury_service.py`, `backend/app/services/payments_compliance_service.py`
  - API exposure: `backend/app/api/v1/treasury.py`, `backend/app/api/v1/payments_compliance.py`
- HMRC payment due date visibility (<7 day alert)
  - Implementation: `frontend/src/App.tsx` (CFO screen), treasury services and obligations payload.

## MoD Audit Requirement Mapping

- Immutable audit trail for agent executions
  - Control: unique `execution_id` per run, tool call logging
  - Implementation: `backend/app/agents/base.py`, `backend/app/models/__init__.py` (`AgentExecutionLog`)
- Report/log integrity
  - Implementation: security event records and audit-ready exports in service layer.

## GDPR Article Mapping

- Article 17 (right to erasure)
  - Endpoint: `DELETE /api/v1/users/{user_id}/personal-data`
  - Implementation: `backend/app/api/v1/users.py`, `backend/app/services/auth_service.py` (`erase_personal_data`)
  - Data flow: PII anonymised in `personal_data_records`; ledger records retained by UUID reference.

## FCA Authorisation Boundary

- v1 payment mode is manual PAIN.001 preparation with final human bank submission.
- Implemented as read/prepare-only agent and API staging (no direct bank execution path).

## SAR Tipping-Off Prevention

- Payments remain in review/frozen compliance flow where required; SAR details restricted to authorised pathway.
- Operational controls are documented in payment compliance service and compliance docs.

## IFRS 9 Hedge Accounting Mapping

- Service logic: `backend/app/services/hedge_service.py`
- Test coverage: `backend/tests/test_hedge.py`

## Cyber Essentials Plus Mapping

- Secure headers middleware: `backend/app/main.py`
- Dependency scans: `.github/workflows/ci.yml`
- Password policy + lockout + MFA: `backend/app/services/auth_service.py`, `backend/app/api/v1/auth.py`
- Tenant isolation + IP allowlisting: `backend/app/core/database.py`, `backend/app/main.py`
