# Project Folder Structure (Phase 1)

## Root
- `/README.md` — project overview and Phase 1 scope.
- `/.env.example` — complete environment variable template and generation guidance.
- `/docs/` — architecture, compliance, security, and access-control documentation.
- `/backend/` — backend structure placeholders and database migration assets only.
- `/frontend/` — frontend structure placeholders only (no app code).
- `/infra/` — deployment/config placeholders for Railway/Vercel/CI.

## Backend
- `/backend/README.md` — backend architecture boundaries and conventions.
- `/backend/alembic/` — Alembic migration framework files.
- `/backend/alembic/versions/` — migration revisions directory.
- `/backend/alembic/versions/20260304_0001_initial_schema.py` — single authoritative schema migration.
- `/backend/app/` — reserved package path for future FastAPI code (empty in Phase 1).
- `/backend/app/domain/` — reserved domain modules for treasury/tax/payment logic.
- `/backend/app/services/` — reserved service-layer modules.
- `/backend/app/api/` — reserved API route modules.
- `/backend/app/security/` — reserved auth/rbac/security modules.
- `/backend/app/models/` — reserved SQLAlchemy model modules (future, optional if using SQL-first).

## Frontend
- `/frontend/README.md` — frontend scope and non-goals for Phase 1.
- `/frontend/src/` — reserved React source root.
- `/frontend/src/features/` — reserved feature modules (cash, payments, tax, compliance).
- `/frontend/src/components/` — reserved shared UI components.
- `/frontend/src/lib/` — reserved client utilities.

## Infrastructure
- `/infra/README.md` — target hosting architecture (Railway + Vercel) and constraints.
- `/infra/ci/` — CI security/pipeline placeholders.
- `/infra/ci/README.md` — dependency scanning and quality gate outline.

## Docs
- `/docs/COMPLIANCE.md` — legal/compliance design, GDPR split-store model, FCA v1 boundary.
- `/docs/RBAC_MATRIX.md` — 8-role permission matrix and deny/allow precedence.
- `/docs/COMPLIANCE_CHECKLIST.md` — requirement-to-control traceability map.
- `/docs/ARCHITECTURE.md` — core architecture principles and data separation diagram.
- `/docs/SECURITY.md` — security controls and vulnerability disclosure policy.
- `/docs/CYBER_ESSENTIALS_PLUS_GAP_ANALYSIS.md` — control-by-control gap analysis.
