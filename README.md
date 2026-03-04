# KuberaTreasury

UK treasury platform for regulated cash visibility, HMRC obligations, payment controls, and audit-grade reporting.

## Architecture

```mermaid
flowchart LR
  CFO[CFO Mobile Dashboard] --> FE[Frontend - Vercel]
  FE --> API[FastAPI API - Railway]
  API --> PG[(PostgreSQL)]
  API --> REDIS[(Redis)]
  WRK[Worker / Cron Agents] --> API
  WRK --> PG
```

## Product Summary

- Security-first multi-tenant treasury operations
- HMRC scheduling and compliance controls
- Four-eyes payment controls and sanctions staging
- AI-assisted read/prepare agents with immutable execution audit
- CFO one-screen 7am mobile view (cash now / where / 90-day outlook)

## Quick Start

### 1) Backend

```powershell
cd backend
K:/KuberaTreasury/.venv/Scripts/python.exe -m pip install -e .[dev]
K:/KuberaTreasury/.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

### 2) Frontend

```powershell
cd frontend
npm install
npm run dev
```

### 3) UAT bootstrap

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:testpass@localhost:55432/kubera_treasury"
K:/KuberaTreasury/.venv/Scripts/python.exe .\scripts\bootstrap_uat_phase4.py --tenant-id 6dfc32c5-8bef-48bd-9753-c8b8aa2dc676 --include-demo-payloads
```

## API Overview

- Auth: login, refresh, MFA setup/verify, password change, logout-all sessions
- Treasury: consolidated positions, liquidity, HMRC obligations, forecasts, board/report exports
- Payments compliance: initiation, approval, sanctions controls, PAIN.001 staging
- User data rights: personal data anonymisation endpoint preserving ledger integrity

Full endpoint catalog: docs/API.md

## Compliance Summary

- HMRC MTD obligations + submissions support
- IFRS 9 hedge controls and tests
- GDPR erasure with financial-record preservation
- Cyber Essentials Plus controls (headers, vuln scanning, secrets policy)
- FCA perimeter boundary documented for manual PAIN.001 mode

Full mapping: docs/COMPLIANCE.md

## Deployment

- Railway: API + worker + postgres + redis (`railway.toml`, `Procfile`)
- Vercel: frontend static build + `/api/*` proxy (`vercel.json`)
- CI/CD: lint, type-check, tests, coverage gate, cross-tenant isolation gate (`.github/workflows/ci.yml`)

## Security

- Responsible disclosure process, supported versions, and rotation policy: docs/SECURITY.md

## Current Model

All internal treasury agents are configured for Claude Sonnet 4.6 (`claude-sonnet-4-6`) and operate in read/prepare mode only.
