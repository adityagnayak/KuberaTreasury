"""
NexusTreasury — Application Configuration
All settings loaded from environment variables via pydantic-settings.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./nexustreasury.db"

    # ── Redis / Cache ────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Encryption / Auth ─────────────────────────────────────────────────────
    # AES_KEY must be 32 bytes, base64-encoded
    AES_KEY: str = "CHANGE_ME_32_BYTE_BASE64_KEY_HERE="
    JWT_SECRET: str = "CHANGE_ME_JWT_SECRET_256_BIT"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 60

    # ── Treasury Settings ─────────────────────────────────────────────────────
    BASE_CURRENCY: str = "EUR"
    SANCTIONS_MATCH_THRESHOLD: float = 0.85
    VARIANCE_ALERT_THRESHOLD: float = 500.0  # percent

    # ── Application Settings ──────────────────────────────────────────────────
    ENVIRONMENT: str = "development"  # development | staging | production
    APP_TITLE: str = "NexusTreasury"
    APP_VERSION: str = "1.0.0"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # ── CORS / Security ───────────────────────────────────────────────────────
    DEBUG: bool = False

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}")
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def sanctions_threshold_decimal(self) -> Decimal:
        return Decimal(str(self.SANCTIONS_MATCH_THRESHOLD))

    @property
    def variance_threshold_decimal(self) -> Decimal:
        return Decimal(str(self.VARIANCE_ALERT_THRESHOLD))


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton — safe for FastAPI Depends()."""
    return Settings()


# Module-level convenience alias
settings = get_settings()
