# Compliance Checklist Traceability (Requirement → Control Mapping)

| Requirement | Control Type | Implemented In | Planned Endpoint/Service |
| --- | --- | --- | --- |
| MTD VAT HMRC API v1.0 compatibility | Schema + audit logging | `hmrc_obligations`, `hmrc_api_submissions` | `POST /api/v1/hmrc/vat/submissions`, `GET /api/v1/hmrc/vat/obligations` |
| MTD Corporation Tax readiness (Apr 2026) | Schema readiness | `hmrc_obligations` (`tax_type=CT`), `tax_profiles` | `POST /api/v1/hmrc/ct/submissions` |
| CT instalment quarterly or 9 months post year end | Business profile config | `tax_profiles.is_large_company_for_ct`, `tax_profiles.ct_due_rule` | `TaxSchedulerService` |
| PAYE 19th/22nd monthly forecast autopopulation | Forecast calendar model | `paye_calendar_entries`, `forecast_cashflows` | `ForecastPopulationService` |
| CIR flag at >£2M net group interest | Computed compliance control | `corporate_interest_restrictions.is_above_threshold` | `GET /api/v1/compliance/cir` |
| Transfer pricing timestamp log | Immutable transaction log | `intercompany_transactions.logged_at`, `tp_document_hash` | `POST /api/v1/intercompany/logs` |
| VAT coding on every transaction | Non-null constraint | `ledger_events.vat_code` | `POST /api/v1/ledger/events` |
| Currency revaluation with HMRC rates | Referential integrity | `currency_revaluations.hmrc_exchange_rate_id`, `exchange_rates_hmrc` | `POST /api/v1/ledger/revaluations` |
| HMRC payment reference format rules | Check constraints | `tax_payment_references.ck_tax_payment_reference_format` | `POST /api/v1/hmrc/payment-references/validate` |
| OFFICIAL only (no OFFICIAL-SENSITIVE in v1) | Enum + check constraint | `classification_level` enum + table checks | `ClassificationPolicyService` |
| Immutable audit trail exportable signed PDF | Trigger immutability + export metadata | `audit_events`, `audit_export_jobs`, immutability triggers | `POST /api/v1/audit/exports` |
| Segregation of duties in code | DB trigger + role controls | `payment_approvals` trigger + RBAC tables | `PaymentApprovalService` |
| Four-eyes approval all payments | Threshold + trigger | `payment_policies.required_approvals>=2`, trigger function | `POST /api/v1/payments/{id}/approve` |
| Payment policy thresholds by amount/currency | Configurable policy table | `payment_policies` | `PUT /api/v1/payments/policies` |
| RBAC explicit deny > allow > default deny | Policy model | `permissions`, `roles`, `role_permissions(effect)` | `AuthorizationEngine` middleware |
| Session timeout + TOTP + IP allowlisting | Auth/session schema | `auth_sessions`, `auth_factors`, `ip_allowlist_entries` | `AuthService` |
| 7-year HMRC + 10-year MoD retention | Retention policy model | `record_retention_policies`, `contracts.is_mod_contract` | `RetentionSchedulerService` |
| PersonalDataRecord separate from ledger | Data architecture separation | `personal_data_records` vs `ledger_events/counterparties` UUID refs | `GDPRService.eraseSubject()` |
| Erasure keeps ledger intact | Decoupled reference model | no FK from ledger to PII table | `DELETE /api/v1/personal-data/{id}` |
| v1 manual PAIN.001 only (no direct bank API) | Scope boundary + channel enum | `payment_batches.channel=manual_pain001`, `pain001_exports` | `POST /api/v1/payments/pain001/export` |
| FCA authorisation not required for v1 scope | Legal scope control | documented in `COMPLIANCE.md` and channel constraints | `ComplianceAssessmentService` |
| HTTP security headers enforced | App gateway policy | documented baseline (`SECURITY.md`) | `SecurityHeadersMiddleware` |
| Dependency scanning in CI | Pipeline control | `infra/ci/README.md` policy | CI (`pip-audit`, `npm audit`) |
| Secrets rotation + no secrets in git | Operational policy | `.env.example`, `SECURITY.md` | `SecretsManagementRunbook` |
