#!/usr/bin/env bash
# NexusTreasury — Initialize GitHub Repository
# Run after setup_local.sh: bash scripts/init_github.sh

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${CYAN}[git]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
fail() { echo -e "${RED}[error]${NC} $1"; exit 1; }

# ── Safety checks ─────────────────────────────────────────────────────────────
[[ -f ".gitignore" ]] || fail ".gitignore not found. Are you in the project root?"
[[ ! -f ".env" ]] || warn ".env exists — verify it's listed in .gitignore before pushing"

# ── Init repo ─────────────────────────────────────────────────────────────────
if [[ ! -d ".git" ]]; then
  log "Initializing git repository..."
  git init
  git branch -m main
  ok "Git repo initialized on branch: main"
else
  ok "Git repo already initialized"
fi

# ── Stage .gitignore first ────────────────────────────────────────────────────
log "Committing .gitignore first (to exclude secrets from history)..."
git add .gitignore
git diff --cached --quiet || git commit -m "chore: add .gitignore"

# ── Verify .env not staged ────────────────────────────────────────────────────
if git ls-files --others --exclude-standard | grep -q "^\.env$"; then
  ok ".env is correctly untracked"
elif git diff --cached --name-only | grep -q "^\.env$"; then
  fail ".env is staged! Remove it: git reset HEAD .env"
fi

# ── Stage all files ───────────────────────────────────────────────────────────
log "Staging all files..."
git add .

# Double-check .env is not staged
if git diff --cached --name-only | grep -q "^\.env$"; then
  git reset HEAD .env
  fail ".env was staged and has been unstaged. Please commit again."
fi

ok "All files staged (excluding .env and other ignored files)"
git diff --cached --stat

# ── Commit ────────────────────────────────────────────────────────────────────
log "Creating initial commit..."
git commit -m "feat: initial NexusTreasury implementation

Implements full treasury management system migrated from Colab to production VSCode/GitHub structure.

Phases implemented:
- Phase 1: CAMT.053/MT940 ingestion, audit immutability, gap detection, period locks
- Phase 2: Cash positioning, multi-currency conversion, liquidity forecasting, variance alerts
- Phase 3: Payment factory, Four-Eyes approval, sanctions screening (fuzzy), PAIN.001 export
- Phase 4: FX risk (VaR, flash crash detection), debt ledger, transfer pricing, GL engine
- Phase 5: RBAC permission matrix, E-BAM mandate lifecycle, concurrency with WAL mode

Infrastructure:
- FastAPI with SQLAlchemy 2.0, pydantic-settings
- SQLite (dev) / PostgreSQL (prod) with automatic detection
- Redis / Upstash with in-memory fallback
- GitHub Actions CI/CD with lint, typecheck, test (80% coverage), Railway deploy
- VSCode workspace configuration

Edge cases: 20 treasury-specific edge cases preserved from original implementation."

ok "Initial commit created"

# ── Remote ────────────────────────────────────────────────────────────────────
echo ""
warn "Next steps — run these commands manually:"
echo ""
echo "  1. Create a new repo on GitHub (do NOT initialize with README)"
echo "  2. Add the remote:"
echo "       git remote add origin https://github.com/YOUR_USERNAME/nexustreasury.git"
echo ""
echo "  3. Push:"
echo "       git push -u origin main"
echo ""
echo "  4. Add GitHub secrets (Settings → Secrets → Actions):"
echo "       RAILWAY_TOKEN    → from railway.app dashboard"
echo ""
echo "  5. Connect Railway to your GitHub repo:"
echo "       railway login"
echo "       railway link"
echo ""
echo -e "${GREEN}Repository ready for push!${NC}"
