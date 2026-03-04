"""Application configuration — loaded once at startup from environment."""
from __future__ import annotations

from decimal import Decimal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    APP_NAME: str = "KuberaTreasury"
    APP_ENV: str = "development"
    API_VERSION: str = "v1"
    FRONTEND_BASE_URL: str = "http://localhost:5173"

    # --- DB ---
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/kuberatreasury"
    REPORTING_DATABASE_URL: str | None = None
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 20

    # --- Auth ---
    # USER ACTION REQUIRED (production): set a strong random secret via environment variable.
    JWT_SECRET_KEY: str = "change-me-in-production-must-be-32-chars-min"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_TTL_MINUTES: int = 15
    BCRYPT_ROUNDS: int = 12
    # USER ACTION REQUIRED: set AES-256 key material (recommended: 32-byte random value encoded/managed per your KMS policy).
    MFA_TOTP_ENCRYPTION_KEY: str | None = None

    # --- AI ---
    # USER ACTION REQUIRED when AI_PROVIDER=claude: add Anthropic API key in environment.
    ANTHROPIC_API_KEY: str | None = None
    # USER ACTION REQUIRED when AI_PROVIDER=gemini: add Gemini API key in environment.
    GEMINI_API_KEY: str | None = None
    AI_MODEL_NAME: str = "claude-sonnet-4-6"
    GEMINI_MODEL_NAME: str = "gemini-2.0-flash"
    # Set true to hard-deprecate Gemini provider path without removing code.
    AI_PROVIDER_GEMINI_DEPRECATED: bool = False

    # --- HMRC ---
    HMRC_API_BASE_URL: str = "https://api.service.hmrc.gov.uk"
    HMRC_API_VERSION: str = "v1.0"
    HMRC_EXCHANGE_RATE_BASE_URL: str = (
        "https://www.trade-tariff.service.gov.uk/api/v2/exchange_rates/files"
    )
    HMRC_SANDBOX_MODE: bool = True

    # --- Payments ---
    PAYMENT_INITIATION_MODE: str = "manual_pain001_only"

    # --- CIR thresholds ---
    CIR_ALERT_THRESHOLD: Decimal = Decimal("1500000.00")
    CIR_HARD_FLAG_THRESHOLD: Decimal = Decimal("2000000.00")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def non_empty(cls, v: str) -> str:
        # Allow SQLite URLs for testing
        if not v:
            raise ValueError("DATABASE_URL must be set")
        return v


settings = Settings()  # type: ignore[call-arg]
