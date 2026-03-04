# SECURITY

## Vulnerability Disclosure Policy

- Report vulnerabilities to: security@kubera.example
- Include: reproduction steps, impacted endpoint/module, severity estimate
- SLA:
  - Critical: acknowledge within 1 business day, mitigate within 72h
  - High: acknowledge within 2 business days, mitigate within 7 days
  - Medium/Low: triaged into release cycle
- Good-faith research safe harbor applies for non-destructive testing.

## Supported Versions

- `main` (latest): fully supported
- Prior tags: security fixes best-effort only

## Cyber Essentials Plus Controls Summary

1. Firewalls / boundary controls
   - Enforced through Railway/Vercel managed ingress and service isolation.
2. Secure configuration
   - Strict security headers in backend middleware.
3. Access control
   - JWT + bcrypt + TOTP + role-aware MFA enforcement.
4. Malware protection
   - Managed runtime baseline plus dependency audit gates.
5. Patch management
   - CI dependency vulnerability scans (`pip-audit`, `npm audit`).

## Secrets Rotation Policy

- Rotate all runtime secrets every 90 days or immediately on compromise.
- Never store secrets in source control.
- Use platform secret manager for:
  - `JWT_SECRET_KEY`
  - `MFA_TOTP_ENCRYPTION_KEY`
  - `HMRC_TOKEN_ENCRYPTION_KEY`
  - API keys (Anthropic, Gemini)
- Rotation must include restart/rollout and post-rotation auth validation.
