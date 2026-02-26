#!/usr/bin/env bash
# NexusTreasury — Local Development Setup
# Run once after cloning: bash scripts/setup_local.sh

set -euo pipefail

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${CYAN}[setup]${NC} $1"; }
ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
fail() { echo -e "${RED}[error]${NC} $1"; exit 1; }

# ── Checks ───────────────────────────────────────────────────────────────────
command -v python3 &>/dev/null || fail "python3 not found. Install Python 3.11+."
PY_VERSION=$(python3 -c "import sys; print(sys.version_info.minor)")
[[ "$PY_VERSION" -ge 10 ]] || fail "Python 3.10+ required (found 3.${PY_VERSION})."

# ── Virtual environment ───────────────────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
  log "Creating virtual environment..."
  python3 -m venv .venv
  ok "Created .venv"
else
  ok ".venv already exists, skipping creation"
fi

source .venv/bin/activate

# ── Dependencies ──────────────────────────────────────────────────────────────
log "Installing production dependencies..."
pip install --quiet -r requirements.txt
ok "Production dependencies installed"

log "Installing dev dependencies..."
pip install --quiet -r requirements-dev.txt
ok "Dev dependencies installed"

# ── Environment file ──────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
  log "Creating .env from .env.example..."
  cp .env.example .env

  log "Generating AES_KEY..."
  AES_KEY=$(python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())")
  sed -i.bak "s|your-32-byte-base64-encoded-key-here|$AES_KEY|" .env

  log "Generating JWT_SECRET..."
  JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i.bak "s|your-random-256-bit-secret-here|$JWT_SECRET|" .env

  rm -f .env.bak
  ok ".env created with generated secrets"
else
  ok ".env already exists, skipping"
fi

# ── Database ──────────────────────────────────────────────────────────────────
log "Initializing database..."
python3 scripts/init_db.py
ok "Database initialized"

log "Seeding demo data..."
python3 scripts/seed_data.py
ok "Demo data seeded"

# ── Tests ─────────────────────────────────────────────────────────────────────
log "Running test suite..."
pytest tests/ -v --tb=short
ok "All tests passed"

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Activate your venv:  source .venv/bin/activate"
echo "  2. Start the API:       uvicorn app.main:app --reload"
echo "  3. View API docs:       http://localhost:8000/docs"
echo "  4. Health check:        http://localhost:8000/health"
