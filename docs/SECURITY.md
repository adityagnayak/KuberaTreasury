# SECURITY.md

## Security Baseline

- TLS-only transport.
- Required HTTP headers:
  - Content-Security-Policy
  - Strict-Transport-Security
  - X-Frame-Options: DENY
  - X-Content-Type-Options: nosniff
- JWT-based auth with short-lived access tokens and revocable sessions.
- Password hashing with bcrypt (cost >= 12).
- TOTP MFA ready from v1 schema.
- Tenant-level IP allowlisting.

## Dependency and Supply Chain Controls

- CI must fail on unresolved critical vulnerabilities:
  - `pip-audit` for Python dependencies
  - `npm audit` for frontend dependencies
- Lockfiles required in Phase 2 implementation.
- SBOM generation recommended prior to production.

## Secrets Management Policy

- No secrets in code, repository, or CI logs.
- Secrets managed via platform secret stores (Railway/Vercel).
- Rotation interval: every 90 days minimum, immediate on incident.
- Signing and encryption keys versioned and revocable.

## Vulnerability Disclosure Policy

- Contact: `security@kubera.example`
- Acknowledge reports within 3 business days.
- Provide remediation timeline based on severity:
  - Critical: mitigation within 24–72h
  - High: mitigation within 7 days
  - Medium: mitigation within 30 days
  - Low: backlog and track
- Safe harbor for good-faith researchers performing non-destructive testing.
