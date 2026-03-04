# KuberaTreasury

Commercial SaaS Treasury Management System for UK mid-market companies.

This repository is intentionally **schema-and-architecture only (Phase 1)**.
No application code is included.

## Phase 1 Artifacts
- PostgreSQL schema in a single Alembic migration
- Project structure definition
- Environment variable template
- RBAC permission matrix
- Compliance checklist mappings
- Personal data separation architecture
- Cyber Essentials Plus gap analysis

## Stack (Target)
- Backend: FastAPI (Python 3.12) on Railway
- Frontend: React 18 + Vite on Vercel
- Database: PostgreSQL (Railway managed)
- Cache: Redis (Railway managed)
- AI: Claude Sonnet 4.6 (`claude-sonnet-4-6`) via Anthropic API
- Auth: JWT + bcrypt + TOTP MFA
- Standards: ISO 20022 (CAMT.053, PAIN.001), ISO 4217

## Go-Live Secrets Checklist

Set these values in your deployment secret manager before production cutover:

- [ ] `JWT_SECRET_KEY` (32-byte random secret; example generation: `openssl rand -hex 32`)
- [ ] `MFA_TOTP_ENCRYPTION_KEY` (AES-256 key material, 32 random bytes)
- [ ] `ANTHROPIC_API_KEY` (required when `AI_PROVIDER=claude`)
- [ ] `GEMINI_API_KEY` (required when `AI_PROVIDER=gemini`)
- [ ] `AI_PROVIDER` (`ollama` for UAT, switch to `claude` or `gemini` for production)
- [ ] `AI_PROVIDER_GEMINI_DEPRECATED` (set `true` when you want to sunset Gemini path)
- [ ] `AUDIT_PDF_SIGNING_PRIVATE_KEY` (KMS/secret manager only; never commit)
- [ ] `AUDIT_PDF_SIGNING_KEY_ID` (matching signing key identifier)
- [ ] `HMRC_CLIENT_ID` and `HMRC_CLIENT_SECRET`
- [ ] `DATABASE_URL` and `REPORTING_DATABASE_URL`

Reference template and inline intervention markers:

- `.env.example`
- `backend/app/core/config.py`
- `backend/app/services/treasury_service.py`

## KMS Setup Examples (Audit PDF Signing)

Use a managed key service in production and store references/secrets in your platform secret manager.

### AWS KMS

1) Create key

```bash
aws kms create-key --description "KuberaTreasury PDF signing key"
```

2) Create alias

```bash
aws kms create-alias --alias-name alias/kubera-pdf-signing --target-key-id <KEY_ID>
```

3) Set environment secrets

- `AUDIT_PDF_SIGNING_KEY_ID=alias/kubera-pdf-signing`
- `AUDIT_PDF_SIGNING_PRIVATE_KEY=<reference/token/credential from your secrets workflow>`

### Azure Key Vault

1) Create key

```bash
az keyvault key create --vault-name <VAULT_NAME> --name kubera-pdf-signing --kty RSA
```

2) Set environment secrets

- `AUDIT_PDF_SIGNING_KEY_ID=kubera-pdf-signing`
- `AUDIT_PDF_SIGNING_PRIVATE_KEY=<reference/token/credential from your secrets workflow>`

### Google Cloud KMS

1) Create key ring and key

```bash
gcloud kms keyrings create kubera-ring --location=global
gcloud kms keys create kubera-pdf-signing --location=global --keyring=kubera-ring --purpose=asymmetric-signing
```

2) Set environment secrets

- `AUDIT_PDF_SIGNING_KEY_ID=projects/<PROJECT>/locations/global/keyRings/kubera-ring/cryptoKeys/kubera-pdf-signing`
- `AUDIT_PDF_SIGNING_PRIVATE_KEY=<reference/token/credential from your secrets workflow>`

## UAT vs Production (Important)

- **UAT** means *User Acceptance Testing*: a pre-production environment where business users validate workflows with non-production data.
- In UAT, temporary/local signing credentials are acceptable for speed, but they must be isolated and disposable.
- In production, use KMS/HSM-backed keys only, with rotation and access controls.
- Never reuse UAT keys in production.

### Generate temporary UAT signing keys (Windows PowerShell)

From repository root:

```powershell
.\scripts\generate_uat_signing_key.ps1
```

Optional custom output folder:

```powershell
.\scripts\generate_uat_signing_key.ps1 -OutputDirectory ".\tmp\uat-keys"
```

The script prints ready-to-paste `.env` lines for:

- `AUDIT_PDF_SIGNING_KEY_ID`
- `AUDIT_PDF_SIGNING_PRIVATE_KEY`

### Cleanup temporary UAT signing keys

Interactive cleanup:

```powershell
.\scripts\cleanup_uat_signing_keys.ps1
```

Non-interactive cleanup:

```powershell
.\scripts\cleanup_uat_signing_keys.ps1 -Force
```

## Note
Phase 2 (application/service implementation) should only start after explicit confirmation.
