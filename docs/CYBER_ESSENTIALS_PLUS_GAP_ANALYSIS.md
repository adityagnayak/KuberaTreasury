# Cyber Essentials Plus Gap Analysis (Architecture-Level)

## 1) Firewalls and Internet Gateways

- Current design state: platform-managed ingress (Railway/Vercel) assumed.
- Gaps:
  - Network policy definitions not yet codified (source CIDRs, admin path restrictions).
  - No explicit WAF/CDN policy documented.
- Actions:
  - Define ingress allow/deny matrix by environment.
  - Add infrastructure-as-code baseline for gateway controls.

## 2) Secure Configuration

- Current design state: secure headers, session timeout, MFA-ready, IP allowlist schema.
- Gaps:
  - Hardening baselines for OS/container images not documented.
  - CIS benchmark alignment not yet evidenced.
- Actions:
  - Create hardening standard per runtime.
  - Add configuration compliance checks in CI/CD.

## 3) User Access Control

- Current design state: robust RBAC model with explicit deny precedence.
- Gaps:
  - Joiner/mover/leaver operational process not documented.
  - Break-glass and privileged access workflow missing.
- Actions:
  - Add IAM runbook with approval trails.
  - Enforce periodic access recertification.

## 4) Malware Protection

- Current design state: no endpoint controls specified in architecture docs.
- Gaps:
  - Developer workstation EDR policy undefined.
  - Build artifact malware scanning not specified.
- Actions:
  - Mandate managed endpoints + EDR for privileged users.
  - Add artifact/container scanning gates.

## 5) Security Update Management

- Current design state: dependency scanning policy declared.
- Gaps:
  - Patch SLAs and ownership matrix incomplete.
  - No automated dependency update policy captured.
- Actions:
  - Define patch windows by severity.
  - Introduce Dependabot/Renovate with approval policy.

## 6) Logging and Monitoring (CE+ Evidence Expectation)

- Current design state: immutable audit logs and export metadata in schema.
- Gaps:
  - SIEM forwarding/alerting rules not yet defined.
  - Incident response runbooks not yet documented.
- Actions:
  - Integrate central log pipeline and high-risk alerts.
  - Publish incident handling and breach notification procedures.

## 7) Backup and Recovery (Operational Assurance)

- Current design state: data retention modeled, no recovery tests defined.
- Gaps:
  - RPO/RTO targets not specified.
  - Restore drill cadence missing.
- Actions:
  - Define and test backup/restore strategy quarterly.

## Overall Readiness (Phase 1)

- Strengths: strong data model controls for tenancy, audit immutability, SoD, and tax evidence.
- Main gaps: operational controls, infrastructure policy-as-code, endpoint/device assurances, and formal evidence packs.
- CE+ trajectory: feasible for Phase 2/3 with operationalisation of documented controls.
