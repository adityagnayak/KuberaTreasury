# API Reference

## Auth

- `POST /api/v1/auth/login`
  - Auth: none
  - Request: `tenant_id`, `email`, `password`, optional `totp_code|backup_code`
  - Response: access token + refresh cookie (`httpOnly`)
  - Errors: `401 invalid credentials`, `401 mfa required`, `401 lockout`

- `POST /api/v1/auth/refresh`
  - Auth: refresh cookie
  - Response: new access token
  - Errors: `401 invalid/expired/revoked session`

- `POST /api/v1/auth/mfa/setup`
  - Auth: bearer access token
  - Response: otpauth URI + 10 backup codes

- `POST /api/v1/auth/mfa/verify`
  - Auth: bearer access token
  - Request: 6-digit TOTP code
  - Response: verified boolean

- `POST /api/v1/auth/logout-all`
  - Auth: bearer access token
  - Response: revoked session count

- `POST /api/v1/auth/change-password`
  - Auth: bearer access token
  - Request: current_password, new_password
  - Policy: 12 chars, upper/lower/number/special, no reuse of last 12

## Users

- `DELETE /api/v1/users/{user_id}/personal-data`
  - Auth: bearer access token
  - Behaviour: anonymises personal data records; preserves financial records
  - Response: anonymised record count + audit event

## Treasury

- `POST /api/v1/treasury/position`
- `POST /api/v1/treasury/liquidity`
- `POST /api/v1/treasury/hmrc/obligations`
- `POST /api/v1/treasury/ai/forecast`
- `POST /api/v1/treasury/reports/daily-variance`
- `POST /api/v1/treasury/reports/weekly-summary`
- `POST /api/v1/treasury/reports/monthly-board-pack`

## Payments Compliance

- `POST /api/v1/payments/...` family for initiation, approval, sanctions, SAR, PAIN.001 staging

## Rate Limits

- Default recommendation: apply gateway-level limits (e.g., 60 req/min/user for auth endpoints)
- Burst limits and WAF policies should be configured at platform ingress.
