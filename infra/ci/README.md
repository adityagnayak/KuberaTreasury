# CI/CD Pipeline

This project uses `.github/workflows/ci.yml` with four stages:

1. **Quality checks**
	- Backend: `ruff`, `mypy --strict`, `pytest` with coverage gate (`>=85%`)
	- Frontend: `npm install`, `npm run typecheck`, `npm run build`
2. **Security gates**
	- `pip-audit` against installed backend environment
	- `npm audit --audit-level=high`
	- `gitleaks` secret scan
3. **Staging deploy** (automatic on `main`)
4. **Production deploy** (manual via workflow dispatch + environment approval)

## Required GitHub Environments

- `staging`
- `production`

Configure environment protection rules as needed (required reviewers recommended for `production`).

## Required GitHub Secrets

### Shared deployment secrets
- `RAILWAY_TOKEN`
- `RAILWAY_PROJECT_ID`
- `RAILWAY_STAGING_ENVIRONMENT_ID`
- `RAILWAY_PRODUCTION_ENVIRONMENT_ID`
- `VERCEL_TOKEN`
- `VERCEL_ORG_ID`
- `VERCEL_PROJECT_ID`

### Optional smoke-test URLs
- `STAGING_API_HEALTH_URL` (for example: `https://staging-api.example.com/healthz`)
- `PRODUCTION_API_HEALTH_URL` (for example: `https://api.example.com/healthz`)

If smoke-test secrets are not set, those checks are skipped.

## Trigger Model

- Pull requests to `main`: quality + security only (no deploy).
- Push to `main`: quality + security + staging deploy.
- Manual (`workflow_dispatch`) with `deploy_production=true`: full pipeline including production deploy.

## Notes

- Frontend install uses `npm install` to avoid lockfile mismatch failures.
- Python vulnerability scanning installs backend dependencies first, then runs `pip-audit`.
