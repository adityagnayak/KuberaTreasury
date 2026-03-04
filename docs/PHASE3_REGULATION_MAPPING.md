# Phase 3 Regulation Mapping

This document maps Phase 3 treasury components to the controlling regulation or standard requirement.

| Component | Path | Requirement Satisfied |
|---|---|---|
| Consolidated group liquidity, position splits, maturity buckets | `backend/app/services/treasury_service.py` (`consolidated_position`) | Internal treasury policy for daily liquidity management and concentration visibility; supports UK governance expectations for prudential cash monitoring |
| Intraday sweep simulation | `backend/app/services/treasury_service.py` (`simulate_intraday_sweep`) | Operational cash risk control under ISO 9001 process control principles (§8.1/§8.5) |
| Available liquidity calculation (`cash + undrawn - queue`) | `backend/app/services/treasury_service.py` (`available_liquidity_and_alerts`) | Treasury liquidity governance control and covenant monitoring expectations |
| Alert engine (minimum balance, overdraft 80%, concentration >40%, covenant headroom 10%) | `backend/app/services/treasury_service.py` (`available_liquidity_and_alerts`) | UK internal control expectations (SOX-style control design), covenant early warning governance |
| HMRC VAT scheduling (quarterly and MTD monthly) | `backend/app/services/treasury_service.py` (`populate_hmrc_obligations`) | HMRC MTD VAT obligations timing rules |
| HMRC Corporation Tax due dates (standard and large-company instalments) | `backend/app/services/treasury_service.py` (`populate_hmrc_obligations`) | HMRC Corporation Tax payment timetable |
| PAYE/NIC and CIS due date mode (19th cheque / 22nd electronic) | `backend/app/services/treasury_service.py` (`populate_hmrc_obligations`) | HMRC PAYE and CIS payment deadlines |
| Companies House confirmation statement scheduling | `backend/app/services/treasury_service.py` (`populate_hmrc_obligations`) | Companies House filing cadence requirements |
| HMRC payment reference auto-population | `backend/app/services/treasury_service.py` (`_vat_reference`, `_ct_reference`, `_paye_reference`, `_cis_reference`, `_ch_reference`) | HMRC payment traceability and reconciliation controls |
| AI provider switch (`ollama` UAT / `claude` or `gemini` production) with deprecation control | `backend/app/services/treasury_service.py` (`process_ai_forecast`) + environment variables `AI_PROVIDER`, `AI_PROVIDER_GEMINI_DEPRECATED` | Controlled deployment and environment segregation (ISO 27001/ISO 9001 change control alignment) |
| GDPR pseudonymisation of account IDs (SHA-256) | `backend/app/services/treasury_service.py` (`process_ai_forecast`) | GDPR Art. 5(1)(c) data minimisation and Art. 32 pseudonymisation security control |
| Restriction to aggregated daily net flows, no IBAN/BIC/counterparty fields | `backend/app/services/treasury_service.py` (`ForecastRowInput`, `process_ai_forecast`) | GDPR minimisation and purpose limitation controls |
| ISO 9001 §8.3 validation pipeline (confidence floor, amount bounds, date horizon) | `backend/app/services/treasury_service.py` (`process_ai_forecast`) | ISO 9001 §8.3 design and development verification/validation controls |
| Human review gating (>£1M or confidence >0.90) | `backend/app/services/treasury_service.py` (`process_ai_forecast`) | Human-in-the-loop governance; model risk management control |
| Rejection log with explicit reason | `backend/app/services/treasury_service.py` (`ForecastRejectedRow`, `process_ai_forecast`) | ISO 9001 evidence of validation outcomes and nonconformance traceability |
| Per-inference audit log | `backend/app/services/treasury_service.py` (`InferenceAuditRecord`, `process_ai_forecast`) | Auditability and accountability requirements (ISO 27001 A.12/A.16 style logging expectations) |
| Daily variance report | `backend/app/services/treasury_service.py` (`daily_variance_report`) | Treasury performance monitoring and forecast governance |
| Weekly treasury summary (including MAPE and HMRC due) | `backend/app/services/treasury_service.py` (`weekly_summary_report`) | Management review evidence under ISO 9001 §9.3 |
| Daily/Weekly PDF+Excel export with signed payload and audit trail | `backend/app/services/treasury_service.py` (`export_daily_variance_report`, `export_weekly_summary_report`, `_export_report`) | Controlled record generation and traceability requirements |
| Monthly board pack PDF+Excel export and report audit event | `backend/app/services/treasury_service.py` (`monthly_board_pack`) | Board governance pack control, evidential record keeping |
| FastAPI exposure of all treasury controls | `backend/app/api/v1/treasury.py` | Controlled API surface for regulated operations and auditability |
| Test coverage enforcing Phase 3 behavior | `backend/tests/test_treasury.py` | Verification evidence supporting ISO 9001 validation expectations |

## Notes

- This mapping is implementation-oriented and should be validated by legal/compliance counsel before regulatory filing or production attestation.
- For formal external assurance (e.g., SOC/ISAE), control wording and evidence references should be linked to policy IDs and control owners.
