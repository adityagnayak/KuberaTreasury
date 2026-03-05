# Security Policy — KuberaTreasury

## Vulnerability Disclosure Policy

KuberaTreasury takes security vulnerabilities seriously. We operate a
responsible disclosure programme and ask researchers to follow the
guidelines below.

### Reporting a Vulnerability

**Email:** security@kuberatreasury.com

Please encrypt sensitive reports using our PGP key (available on request).

Your report should include:

- A clear description of the vulnerability and its potential impact.
- Step-by-step reproduction instructions.
- The affected endpoint, module, or component.
- Your severity estimate (Critical / High / Medium / Low).
- Any proof-of-concept code you are willing to share.

### Response SLAs

| Severity | Acknowledgement | Mitigation target |
|----------|-----------------|-------------------|
| Critical | 1 business day | 72 hours |
| High | 2 business days | 7 days |
| Medium | 5 business days | Next scheduled release |
| Low | 10 business days | Backlog, next release |

### Safe Harbour

Good-faith security research conducted in accordance with this policy
will not result in legal action. Do not access, modify, or exfiltrate
any real user data. Testing must be performed against isolated
environments only.

Out of scope: social engineering, physical attacks, denial-of-service,
spam, and automated crawling of production systems.

---

## Supported Versions

| Version | Branch | Support status |
|---------|--------|----------------|
| latest | `main` | ✅ Fully supported — security patches applied immediately |
| prior tags | `vX.Y.Z` | ⚠️ Best-effort — critical fixes backported where feasible |
| < v1.0 | legacy | ❌ End of life — no security support |

Upgrade to the latest release on `main` to receive all security patches.

---

## Cyber Essentials Plus Controls Summary

KuberaTreasury is designed to satisfy the five HMG Cyber Essentials Plus
control themes. Independent technical verification is required before
claiming certification.

### 1. Boundary Firewalls and Internet Gateways

- Production traffic is routed through managed ingress (Railway / Vercel)
  with no directly-exposed database or internal service ports.
- IP allowlisting is enforced per-tenant via `IpAllowlistMiddleware`
  (`backend/app/main.py`).
- `IpAllowlistEntry` model supports CIDR ranges for office egress blocks.

### 2. Secure Configuration

- OWASP security response headers applied to every request by
  `SecurityHeadersMiddleware` (`backend/app/core/middleware.py`):
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
  - `Content-Security-Policy: default-src 'self'; …; frame-ancestors 'none'`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=()`
  - `Cache-Control: no-store` (all `/api/*` routes)
- `docs_url` and `redoc_url` disabled in production (`APP_ENV=production`).
- Default credentials and placeholder secrets must be replaced before deployment
  (see Secrets Rotation below).

### 3. Access Control

- Authentication: bcrypt-hashed passwords (minimum 12 rounds), TOTP MFA
  (HMAC-SHA1, 30-second window), backup codes (PBKDF2-SHA256).
- Authorisation: JWT access tokens (HS256, 60-minute TTL) + refresh tokens
  (30-day TTL, stored as HTTP-only cookies).
- Role-based access control enforced at the dependency level
  (`backend/app/core/dependencies.py`).
- SAR endpoints gated behind a dedicated `_require_compliance_officer`
  dependency that is not shared with any other router (POCA 2002 s.333A).
- Account lockout after configurable failed attempts; brute-force events
  recorded in `LoginAttempt` and `SecurityEvent` tables.
- Tenant data isolation enforced at the SQLAlchemy `do_orm_execute` layer
  (`backend/app/core/database.py`).

### 4. Malware Protection

- Managed runtime baseline on Railway / Vercel.
- Python dependencies pinned with lower-bound version constraints;
  `pip-audit` runs on every CI push to detect known CVEs.
- `npm audit` runs against all frontend dependencies in CI.

### 5. Patch Management

- Dependency vulnerability scanning (`pip-audit`, `npm audit`) is a
  required CI gate — builds fail on high-severity findings.
- OS and runtime patches are applied automatically by the managed
  platform (Railway / Vercel).
- Security patches for in-house code are released within the SLAs
  defined above.

Full gap-analysis and evidence mapping: `docs/CYBER_ESSENTIALS_PLUS_GAP_ANALYSIS.md`.

---

## Secrets Rotation Schedule

All secrets must be rotated on the schedule below **and** immediately upon
any suspected or confirmed compromise.

| Secret | Environment variable | Rotation interval | Minimum length / spec |
|--------|---------------------|-------------------|------------------------|
| JWT signing key | `JWT_SECRET_KEY` | **90 days** | 32 characters minimum, high-entropy random |
| PII field-encryption key | `PII_ENCRYPTION_KEY` | **90 days** | 32-byte hex-encoded AES-256 key |
| TOTP encryption key | `MFA_TOTP_ENCRYPTION_KEY` | **90 days** | 32-byte AES-256 key |
| HMRC OAuth token encryption key | `HMRC_TOKEN_ENCRYPTION_KEY` | **90 days** | 32-byte hex-encoded AES-256 key |
| Anthropic API key | `ANTHROPIC_API_KEY` | Per provider policy | n/a |
| Gemini API key | `GEMINI_API_KEY` | Per provider policy | n/a |
| Database credentials | `DATABASE_URL` | **180 days** | Managed via platform secret store |
| Audit PDF signing key pair | (key files) | **365 days** | RSA-2048 minimum |

### Rotation Procedure

1. Generate the new secret out-of-band using a cryptographically secure
   random source (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).
2. Update the secret in the platform secret manager (never in source control).
3. Deploy the new value — rolling restart ensures zero downtime.
4. Invalidate all active JWT sessions and HMRC OAuth tokens that were
   signed/encrypted with the previous key.
5. Verify post-rotation with a smoke-test login and payment initiation.
6. Record the rotation event in the change log.

> **Never commit secrets to source control.** The `.env` file is in
> `.gitignore`. Any accidental commit must be treated as a compromise:
> rotate immediately and purge from git history.
