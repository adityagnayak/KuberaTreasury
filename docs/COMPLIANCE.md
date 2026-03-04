# COMPLIANCE.md

## Regulatory Scope (UK)

- HMRC MTD for VAT: architecture supports HMRC API `v1.0` obligations + submissions logs.
- HMRC MTD for Corporation Tax (Apr 2026 readiness): schema includes CT obligations, references, and submission logging.
- CT instalment handling: tax profile captures large-company rule (quarterly instalments) vs standard due rule.
- PAYE calendar support: monthly due dates (19th/22nd) are represented in dedicated forecast-linked table.
- Corporate Interest Restriction: threshold-based monitoring with computed flag above £2M.
- Transfer pricing evidence: all intercompany entries are timestamped with optional documentation hash/URI.
- VAT code enforcement: every ledger event has non-null VAT classification.
- HMRC payment references: format-validated by tax type for CT/VAT/PAYE/CIS.

## MoD Classification and Retention

- Data classification enum only allows `PUBLIC` and `OFFICIAL` in v1.
- `OFFICIAL-SENSITIVE` is explicitly blocked via check constraints.
- Retention policy table supports 7-year HMRC baseline and 10-year MoD contract records.

## Immutable Audit + Segregation of Duties

- Immutable tables: `audit_events`, `ledger_events`, `hmrc_api_submissions`, `ai_inference_logs`.
- DB triggers block UPDATE/DELETE to enforce non-deletable logs.
- Four-eyes payment control enforced at DB trigger level:
  - minimum two approvals,
  - creator cannot approve own payment.
- Approval thresholds captured in payment policy engine by currency and amount.

## GDPR Design (Pseudonymised Ledger)

- PII lives only in `personal_data_records` keyed by `personal_data_id` UUID.
- Financial/ledger records store only UUID references (no enforced FK to permit lawful erasure).
- Erasure flow:
  1. delete or anonymise row in `personal_data_records`,
  2. keep immutable financial ledger/audit rows containing UUID references.
- Result: compatible with HMRC retention obligations while enabling GDPR Article 17 erasure handling.

## FCA Boundary (v1)

- Payment initiation in v1 is **manual PAIN.001 file generation only**.
- No direct API-based payment initiation to banks is included in scope.
- On that basis, v1 is positioned outside regulated payment initiation service activity.
- Legal basis must be validated by regulated counsel before go-live and at each scope change.

## Security Baseline Controls

- HTTP headers mandated: CSP, HSTS, X-Frame-Options, X-Content-Type-Options.
- Dependency scanning in CI: `pip-audit` and `npm audit` required gates.
- Secrets policy: rotation, no secrets in source control, and signing key lifecycle.
- Vulnerability disclosure process defined in `SECURITY.md`.

## Phase 3 Mapping (Liquidity, HMRC Forecasting, AI)

Detailed component-to-regulation traceability is captured in `docs/PHASE3_REGULATION_MAPPING.md`.

- Group liquidity position and maturity buckets (`same day`, `1-7`, `8-30`, `31-90`, `90+`) implemented in `backend/app/services/treasury_service.py` (`consolidated_position`).
- Intraday sweep simulation and available liquidity (`cash + undrawn facilities - payment queue`) implemented in `treasury_service.py` (`simulate_intraday_sweep`, `available_liquidity_and_alerts`).
- Alert engine coverage:
  - minimum balance breach,
  - overdraft approach at 80% limit,
  - concentration risk above 40% bank concentration,
  - covenant headroom alert at <=10%.
- HMRC scheduling automation in `populate_hmrc_obligations`:
  - VAT due date (month + 7 days after filing period),
  - Corporation Tax standard (`9 months + 1 day`) and large-company quarterly instalments (`months 7,10,13,16`),
  - PAYE/NIC and CIS monthly scheduling,
  - annual Companies House confirmation statement,
  - urgency colour and payment reference generation.
- AI provider controls:
  - provider/model switch (`AI_PROVIDER=ollama` UAT, `claude` or `gemini` production),
  - controlled Gemini deprecation switch (`AI_PROVIDER_GEMINI_DEPRECATED=true`) without code removal,
  - model version `claude-sonnet-4-6` supported.
- GDPR non-negotiables in `process_ai_forecast`:
  - account reference pseudonymisation via SHA-256,
  - processing scope restricted to aggregated daily net flows,
  - no personal data payload fields accepted for inference.
- ISO 9001 §8.3 validation pipeline in `process_ai_forecast`:
  - confidence floor of 0.40,
  - tenant-configurable amount bounds (default ±£50M),
  - forecast date horizon validation,
  - human review flag for >£1M or confidence >0.90,
  - explicit rejection log with reason(s).
- Audit log for every inference produced as `InferenceAuditRecord` including provider, model_version, account_ref_hash, prompt_hash, response_hash, latency_ms, accepted/rejected counts, operator_user_id, tenant_id.
- Human-in-the-loop enforced by design: accepted AI outputs are returned as `pending_human_review`; no direct ledger write path is implemented in this service.
- Reporting controls:
  - daily variance report (`forecast vs actual` by entity/currency),
  - weekly treasury summary (movement, net flows, FX impact, HMRC due this week, MAPE),
  - monthly board pack export with PDF + Excel payloads and report generation audit metadata.
