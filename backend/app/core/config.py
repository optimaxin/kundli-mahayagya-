"""Application configuration.

All configuration is read from environment variables (optionally from a local
``.env`` file). No secrets are hard-coded: development defaults are only
accepted when ``APP_ENV`` is ``development`` or ``test``; production start-up
fails fast if a required secret is missing or weak.
"""

from __future__ import annotations

import base64
from datetime import date, time
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me-0123456789"  # noqa: S105 - refused when APP_ENV=production
# 32 zero bytes, base64 encoded -- development/test only.
_DEV_DATA_KEY = base64.urlsafe_b64encode(b"\x00" * 32).decode()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    APP_NAME: str = "2151 Kundiya Mahayagya API"
    APP_ENV: Literal["development", "test", "production"] = "development"
    API_V1_PREFIX: str = "/api/v1"
    ENABLE_DOCS: bool = True
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # ------------------------------------------------------------- database
    DATABASE_URL: str = "postgresql+psycopg://mahayagya:mahayagya@localhost:5432/mahayagya"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_STATEMENT_TIMEOUT_MS: int = 15000
    DB_LOCK_TIMEOUT_MS: int = 5000
    # Supabase transaction-mode pooler (port 6543) does not support prepared statements.
    DB_DISABLE_PREPARED_STATEMENTS: bool = False
    DB_ECHO: bool = False

    # ------------------------------------------------------------- supabase
    # Placeholders only. The backend talks to Supabase through DATABASE_URL.
    # SUPABASE_SERVICE_ROLE_KEY must never be sent to any client.
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ------------------------------------------------------------- security
    JWT_SECRET_KEY: str = _DEV_JWT_SECRET
    JWT_ALGORITHM: Literal["HS256", "HS384", "HS512"] = "HS256"
    JWT_ISSUER: str = "mahayagya-api"
    JWT_AUDIENCE: str = "mahayagya-staff"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    SCANNER_TOKEN_EXPIRE_MINUTES: int = 480
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt short-lived secrets
    # (e.g. the QR token inside an idempotent registration replay record).
    DATA_ENCRYPTION_KEY: str = _DEV_DATA_KEY
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    PASSWORD_MIN_LENGTH: int = 12

    CORS_ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    TRUSTED_HOSTS: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    ENABLE_HSTS: bool = False

    # ---------------------------------------------------------- rate limits
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_BACKEND: Literal["memory", "redis"] = "memory"
    REDIS_URL: str = ""
    RATE_LIMIT_REGISTRATION: str = "10/minute"
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_PASS_LOOKUP: str = "10/minute"  # noqa: S105 - not a secret
    RATE_LIMIT_PUBLIC_READ: str = "120/minute"
    RATE_LIMIT_SCANNER: str = "600/minute"
    # Manual pass-ID entry at the gate (camera fallback) -- tighter limit per scanner.
    RATE_LIMIT_SCANNER_MANUAL: str = "60/minute"  # noqa: S105 - not a secret
    ANALYTICS_CACHE_SECONDS: float = 10.0

    # ---------------------------------------------------- admission control
    REGISTRATION_MAX_CONCURRENCY: int = 16
    REGISTRATION_MAX_QUEUE: int = 200
    REGISTRATION_QUEUE_TIMEOUT_SECONDS: float = 10.0

    # ---------------------------------------------------------------- event
    EVENT_NAME: str = "2151 Kundiya Mahayagya"
    EVENT_TIMEZONE: str = "Asia/Kolkata"
    EVENT_START_DATE: date = date(2026, 12, 14)
    EVENT_DAYS: int = 8
    TOTAL_KUNDS: int = 2151
    MAX_MEMBERS_PER_KUND: int = 8
    # Confirmed session times (frontend PLAN.md): 08:00-11:00 and 13:00-16:00 IST.
    MORNING_START: time = time(8, 0)
    MORNING_END: time = time(11, 0)
    AFTERNOON_START: time = time(13, 0)
    AFTERNOON_END: time = time(16, 0)
    BOOKING_CUTOFF_MINUTES: int = 60
    ENFORCE_CHECKIN_WINDOW: bool = True
    # QR is valid only inside the session window +/- 15 minutes.
    CHECKIN_OPENS_MINUTES_BEFORE: int = 15
    CHECKIN_CLOSES_MINUTES_AFTER: int = 15

    # ---------------------------------------------------------- registration
    REQUIRE_IDEMPOTENCY_KEY: bool = True
    IDEMPOTENCY_TTL_HOURS: int = 24
    ENFORCE_UNIQUE_MOBILE_PER_SESSION: bool = True
    # A booking (and a mobile number) may hold only ONE session per day: morning OR afternoon, not both.
    ONE_SESSION_PER_DAY: bool = True
    ALLOCATION_MAX_RETRIES: int = 4

    # ------------------------------------------------------------------- QR
    QR_TOKEN_BYTES: int = 32
    QR_PAYLOAD_PREFIX: str = "MY26."
    QR_PASS_VALID_DAYS_AFTER_EVENT: int = 1

    # -------------------------------------------------------------- reports
    REPORTS_DIR: str = "./var/reports"

    # -------------------------------------------------------- offline node
    OFFLINE_NODE_MODE: bool = False
    OFFLINE_NODE_ID: str = ""
    CLOUD_API_BASE_URL: str = ""
    CLOUD_SYNC_EMAIL: str = ""
    CLOUD_SYNC_PASSWORD: str = ""

    # ------------------------------------------------------------ validators
    @field_validator("DATABASE_URL")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        # Accept plain postgres:// URLs (as shown in the Supabase dashboard).
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @field_validator("CORS_ALLOWED_ORIGINS", "TRUSTED_HOSTS", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                import json

                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        # Empty values (e.g. copied straight from .env.example) fall back to the
        # dev-only defaults outside production; production refuses them below.
        if not self.JWT_SECRET_KEY.strip() and self.APP_ENV != "production":
            self.JWT_SECRET_KEY = _DEV_JWT_SECRET
        if not self.DATA_ENCRYPTION_KEY.strip() and self.APP_ENV != "production":
            self.DATA_ENCRYPTION_KEY = _DEV_DATA_KEY
        if self.APP_ENV == "production":
            problems: list[str] = []
            if self.JWT_SECRET_KEY == _DEV_JWT_SECRET or len(self.JWT_SECRET_KEY) < 32:
                problems.append("JWT_SECRET_KEY must be set to a random value of >= 32 characters")
            if self.DATA_ENCRYPTION_KEY in (_DEV_DATA_KEY, ""):
                problems.append("DATA_ENCRYPTION_KEY must be set (Fernet key)")
            else:
                try:
                    from cryptography.fernet import Fernet

                    Fernet(self.DATA_ENCRYPTION_KEY.encode())
                except ValueError:
                    problems.append("DATA_ENCRYPTION_KEY is not a valid Fernet key")
            if "*" in self.CORS_ALLOWED_ORIGINS:
                problems.append("CORS_ALLOWED_ORIGINS must be an explicit allowlist in production")
            if self.RATE_LIMIT_BACKEND == "redis" and not self.REDIS_URL:
                problems.append("REDIS_URL is required when RATE_LIMIT_BACKEND=redis")
            if problems:
                raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
