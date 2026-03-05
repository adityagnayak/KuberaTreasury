# Compliance Matrix — KuberaTreasury

Each section follows the structure:
**Requirement** | **Implementation** | **File reference** | **Test reference**

---

## 1. HMRC Making Tax Digital (MTD) — VAT

| Attribute | Detail |
|-----------|--------|
| Requirement | MTD for VAT: mandatory digital record-keeping and quarterly submissions via HMRC API (SI 2018/261). Obligations, returns, liabilities, and payments must be retrievable. |
| Implementation | `HmrcMtdService` — OAuth token storage (AES-256-GCM), obligations query, VAT return build (boxes 1–9), return submission, liabilities, payments. Tokens encrypted at rest with tenant-scoped keys. |
| File reference | `backend/app/services/payments_compliance_service.py` · `backend/app/api/v1/payments_compliance.py` |
| Test reference | `backend/tests/test_payments_compliance.py::test_hmrc_vat_return_builder` · `test_hmrc_sandbox_endpoint_and_audit_log` |

---

## 2. HMRC Corporation Tax (CT600)

| Attribute | Detail |
|-----------|--------|
| Requirement | Correct CT reference format (`XXXXXXXXXX A001`, 14 chars) enforced on every payment instructed to HMRC CT account. |
| Implementation | `_validate_hmrc_reference` in `PaymentsComplianceService` rejects malformed CT references before the payment reaches the approval queue. |
| File reference | `backend/app/services/payments_compliance_service.py` |
| Test reference | `backend/tests/test_payments_compliance.py::test_hmrc_reference_formats_enforced` |

---

## 3. HMRC PAYE / CIS

| Attribute | Detail |
|-----------|--------|
| Requirement | PAYE references must be 13 characters; CIS references must begin with a 10-digit UTR. Enforced at payment initiation. |
| Implementation | `_validate_hmrc_reference` pattern checks for `hmrc_tax_type` values `"PAYE"` and `"CIS"`. |
| File reference | `backend/app/services/payments_compliance_service.py` |
| Test reference | `backend/tests/test_payments_compliance.py::test_hmrc_reference_formats_enforced` |

---

## 4. HMRC Transfer Pricing — TIOPA 2010

| Attribute | Detail |
|-----------|--------|
| Requirement | Intercompany transactions must be at arm's-length (±150 bps). Material variances trigger a `TransferPricingError` (HTTP 422). |
| Implementation | `IntercompanyService.record_transaction` validates the transfer-pricing spread before committing an intercompany entry. |
| File reference | `backend/app/services/intercompany_service.py` · `backend/app/core/exceptions.py` |
| Test reference | `backend/tests/test_intercompany.py` |

---

## 5. Corporate Interest Restriction (CIR) — FA 2017

| Attribute | Detail |
|-----------|--------|
| Requirement | UK groups with net interest > £2 m must calculate and track the interest restriction under HMRC CIR rules. |
| Implementation | `TreasuryService` tracks net finance costs and surfaces restriction calculations through the treasury dashboard agent. |
| File reference | `backend/app/services/treasury_service.py` · `backend/app/agents/hmrc_deadlines.py` |
| Test reference | `backend/tests/test_treasury.py` |

---

## 6. IFRS 9 Hedge Accounting

| Attribute | Detail |
|-----------|--------|
| Requirement | Retrospective effectiveness must fall within 80–125 % (IFRS 9 §B6.4.4). Ineffective hedges must be discontinued and the OCI balance recycled to P&L. |
| Implementation | `HedgeService.assess_effectiveness` raises `HedgeEffectivenessError` (HTTP 422) when the ratio breaches the qualifying range. Hedge designation, de-designation, and OCI recycling are modelled as explicit state transitions. |
| File reference | `backend/app/services/hedge_service.py` · `backend/app/core/exceptions.py` |
| Test reference | `backend/tests/test_hedge.py` |

---

## 7. UK GDPR — Articles 5, 17, 30

| Attribute | Detail |
|-----------|--------|
| Requirement | **Art. 5** — data minimisation and accuracy. **Art. 17** — right to erasure within 30 days. **Art. 30** — Record of Processing Activities (RoPA). |
| Implementation | `AuthService.erase_personal_data` anonymises PII fields in `personal_data_records`; ledger entries retain only UUID references. `PersonalDataRecord` model serves as the Art. 30 RoPA store. AES-256-GCM field-level encryption for PII at rest. |
| File reference | `backend/app/services/auth_service.py` · `backend/app/models/__init__.py` · `backend/app/security/encryption.py` · `backend/app/api/v1/users.py` |
| Test reference | `backend/tests/test_gdpr_erasure.py` · `backend/tests/test_personal_data_record.py` · `backend/tests/test_encryption.py` |

---

## 8. POCA 2002 — SAR Obligations (s.330 / s.333A)

| Attribute | Detail |
|-----------|--------|
| Requirement | **s.330** — staff must file a SAR with the NCA when they know or suspect money laundering. **s.333A** — tipping off (disclosing a SAR investigation to the subject) is a criminal offence. |
| Implementation | SAR case creation is fully isolated in `app/api/v1/sar.py` behind a dedicated `_require_compliance_officer` dependency. The payments router (`payments_compliance.py`) never returns `"sar"`, `"suspicious"`, or `"laundering"` in any response field name or value. Frozen payments are labelled `"UNDER_REVIEW"` to non-MLRO users. SAR report bundles pseudonymise all identifiers. |
| File reference | `backend/app/api/v1/sar.py` · `backend/app/api/v1/payments_compliance.py` · `backend/app/services/payments_compliance_service.py` |
| Test reference | `backend/tests/test_sar_isolation.py` · `backend/tests/test_payments_compliance.py::test_sar_tipping_off_prevention_view` |

---

## 9. FCA PSR 2017 — Authorisation Boundary

| Attribute | Detail |
|-----------|--------|
| Requirement | Payment Services Regulations 2017 (SI 2017/752) — Schedule 1 Part 1 defines regulated payment services including Payment Initiation Services (PIS). |
| Implementation | v1 exports ISO 20022 PAIN.001 XML for manual upload by the user. No direct bank API connectivity. This is not a PIS and does not require FCA authorisation. Any v2 direct-initiation capability must obtain authorisation before release. |
| File reference | `docs/FCA_BOUNDARY.md` · `backend/app/services/payments_compliance_service.py` (`export_pain001_batch`) |
| Test reference | `backend/tests/test_payments_compliance.py::test_approval_and_state_progression_to_reconciled` |

---

## 10. Cyber Essentials Plus

| Attribute | Detail |
|-----------|--------|
| Requirement | HMG Cyber Essentials Plus: boundary firewalls, secure configuration, access control, malware protection, patch management — with independent technical verification. |
| Implementation | OWASP security headers middleware (`SecurityHeadersMiddleware`); bcrypt password hashing; TOTP MFA; IP allowlisting per tenant; JWT access/refresh tokens; AES-256-GCM PII encryption; dependency vulnerability scanning (`pip-audit`) in CI. |
| File reference | `backend/app/core/middleware.py` · `backend/app/services/auth_service.py` · `backend/app/security/encryption.py` · `backend/app/main.py` · `docs/CYBER_ESSENTIALS_PLUS_GAP_ANALYSIS.md` |
| Test reference | `backend/tests/test_security_headers.py` · `backend/tests/test_auth_service.py` · `backend/tests/test_encryption.py` |

---

## 11. MoD Audit Trail Requirements

| Attribute | Detail |
|-----------|--------|
| Requirement | Defence customers require an immutable, time-stamped audit trail of all system actions, agent executions, and user activity suitable for forensic investigation. |
| Implementation | Every agent execution produces an `AgentExecutionLog` row with a unique `execution_id`, tenant ID, timestamps, and tool-call payloads. Payment instructions carry an append-only `audit_trail` list. `RegulatoryExportService` generates signed PDF/Excel/JSON bundles with SHA-256 checksums and a verifiable digital signature. |
| File reference | `backend/app/agents/base.py` · `backend/app/models/__init__.py` (`AgentExecutionLog`) · `backend/app/services/payments_compliance_service.py` (`RegulatoryExportService`) |
| Test reference | `backend/tests/test_agents.py` · `backend/tests/test_payments_compliance.py::test_regulatory_export_bundle_and_signature_verification` |
