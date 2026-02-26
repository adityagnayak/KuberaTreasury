# NexusTreasury

A production-grade **Treasury Management System** built with FastAPI, SQLAlchemy 2.0, and Python 3.11+. Handles bank statement ingestion (CAMT.053 / MT940), cash positioning, payment processing with Four-Eyes approval, FX risk management, GL journaling, debt ledger, and E-BAM mandate lifecycle.

---

## Architecture

```mermaid
graph TD
    subgraph API["API Layer (FastAPI)"]
        A[/api/v1/accounts]
        B[/api/v1/payments]
        C[/api/v1/positions]
        D[/api/v1/forecasts]
        E[/api/v1/instruments]
        F[/api/v1/reports]
    end

    subgraph Services["Service Layer"]
        S1[StatementIngestionService]
        S2[PaymentService]
        S3[CashPositioningService]
        S4[LiquidityForecastingService]
        S5[FX Risk / VaR]
        S6[GLMappingEngine]
        S7[DebtInvestmentLedger]
        S8[EBAMService]
        S9[RBACService]
    end

    subgraph Core["Core"]
        C1[DayCount Conventions]
        C2[BusinessDayAdjuster]
        C3[AES-256-GCM Security]
        C4[JWT Auth]
        C5[Custom Exceptions]
    end

    subgraph Infra["Infrastructure"]
        DB[(SQLite / PostgreSQL)]
        Cache[(Redis / Upstash)]
    end

    API --> Services
    Services --> Core
    Services --> DB
    Services --> Cache
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/nexustreasury.git
cd nexustreasury

# 2. Run setup (creates venv, installs deps, generates secrets, seeds DB, runs tests)
bash scripts/setup_local.sh

# 3. Start the API
source .venv/bin/activate
uvicorn app.main:app --reload

# 4. Open interactive docs
open http://localhost:8000/docs
```

---

## Environment Setup

Copy `.env.example` to `.env` and fill in values. The setup script does this automatically and generates secure keys.

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///./nexustreasury.db` |
| `REDIS_URL` | Redis / Upstash URL | `redis://localhost:6379/0` |
| `AES_KEY` | Base64-encoded 32-byte key for credential encryption | *(generated)* |
| `JWT_SECRET` | 256-bit secret for JWT signing | *(generated)* |
| `BASE_CURRENCY` | Reporting currency | `EUR` |
| `SANCTIONS_MATCH_THRESHOLD` | Fuzzy match threshold (0–1) | `0.85` |
| `VARIANCE_ALERT_THRESHOLD` | Forecast variance alert in base currency | `500.0` |
| `ENVIRONMENT` | `development` / `production` | `development` |

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=app --cov-report=html

# Single phase
pytest tests/test_phase1.py -v
```

The full suite covers 63 scenarios across 5 phases. Coverage requirement: **80%**.

---

## API Documentation

After starting the server, visit:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health check**: http://localhost:8000/health

### Key Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/accounts` | List bank accounts |
| `POST` | `/api/v1/payments` | Initiate a payment |
| `POST` | `/api/v1/payments/{id}/approve` | Approve (Four-Eyes) |
| `GET` | `/api/v1/payments/{id}/pain001` | Export PAIN.001 XML |
| `GET` | `/api/v1/positions` | Consolidated cash position |
| `POST` | `/api/v1/forecasts` | Submit liquidity forecast |
| `GET` | `/api/v1/forecasts/variance` | Variance report |
| `POST` | `/api/v1/instruments/interest` | Calculate accrued interest |
| `POST` | `/api/v1/reports/var` | Compute portfolio VaR |
| `POST` | `/api/v1/reports/gl` | Post GL journal event |

---

## Deployment (Railway)

```bash
# 1. Push to GitHub (main branch triggers auto-deploy)
bash scripts/init_github.sh

# 2. Connect Railway to your GitHub repo
railway login
railway link

# 3. Set environment secrets in Railway dashboard:
#    DATABASE_URL  → Railway PostgreSQL plugin (set automatically)
#    REDIS_URL     → Upstash Redis
#    AES_KEY       → generate with: python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
#    JWT_SECRET    → generate with: python -c "import secrets; print(secrets.token_hex(32))"
#    ENVIRONMENT   → production
```

The `Procfile` runs:
```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

---

## Edge Cases Implemented

All 20 treasury-specific edge cases from the original specification:

1. **Duplicate statement detection** — file hash + message_id + legal sequence number
2. **Gap detection** — business-day-aware gap alerts between statement periods
3. **Backdated transactions** — period lock enforcement with PendingPeriodAdjustment routing
4. **UTF-8 encoding** — NFC normalization for remittance info (umlauts, CJK, etc.)
5. **Self-approval hard block** — Four-Eyes: initiator ≠ approver enforced in DB + service
6. **Sanctions fuzzy matching** — SequenceMatcher ≥ 85% threshold catches typos
7. **PAIN.001 format integrity** — IBAN MOD-97 validation, BIC regex, namespace checks
8. **Insufficient funds check** — balance + overdraft_limit before payment initiation
9. **Negative interest GL reversal** — Dr/Cr swap for ECB-style negative rates
10. **Physical pool spread** — debit_rate > credit_rate → bank nets positive spread
11. **Business day roll** — modified_following convention with dual-currency holiday calendars
12. **Variance alert threshold** — 500 EUR default; infinite variance when forecast net = 0
13. **Flash crash detection** — 5% soft alert, 20% hard alert with VaR recalculation
14. **Forward settlement adjustment** — dual-currency holiday calendars for FX forwards
15. **Day-count conventions** — ACT/360, ACT/365, 30/360 (ISDA), ACT/ACT (ISDA)
16. **Transfer pricing** — arm's-length ±150 bps validation on intercompany loans
17. **Concurrent updates** — SQLite WAL mode + advisory locks prevent phantom totals
18. **E-BAM mandate lifecycle** — NoMandateError, ExpiredMandateError, MandateKeyMismatchError
19. **Audit log immutability** — SQLite triggers block UPDATE/DELETE on audit_logs and transactions
20. **RBAC permission matrix** — explicit deny > explicit allow > default deny

---

## Project Structure

```
nexustreasury/
├── app/
│   ├── config.py              # Pydantic BaseSettings
│   ├── database.py            # SQLAlchemy engine + session factory
│   ├── main.py                # FastAPI app, routers, lifespan
│   ├── api/v1/                # Route handlers
│   ├── core/                  # Security, exceptions, day count, business days
│   ├── models/                # SQLAlchemy ORM models
│   ├── services/              # Business logic
│   └── cache/                 # FX rate cache (Redis / in-memory fallback)
├── tests/
│   ├── conftest.py            # Fixtures (db, tokens, fx cache, CAMT samples)
│   └── test_phase*.py         # 63 test scenarios
├── scripts/
│   ├── init_db.py             # Create tables + triggers
│   ├── seed_data.py           # Demo data
│   ├── setup_local.sh         # One-command local setup
│   └── init_github.sh         # Safe git init + first commit
├── .github/workflows/ci.yml   # Lint → typecheck → test → deploy
├── .vscode/                   # VSCode settings + extensions
├── nexustreasury.code-workspace
├── requirements.txt
├── requirements-dev.txt
├── Procfile
└── .env.example
```

---

## License

All Rights Reserved

Copyright (c) ${2026} ${adityagnayak}

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
