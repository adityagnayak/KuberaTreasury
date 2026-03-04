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

## Note
Phase 2 (application/service implementation) should only start after explicit confirmation.
