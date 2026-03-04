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
