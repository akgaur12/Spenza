"""Centralized, typed application configuration.

Every runtime setting is declared here as a `pydantic-settings` field and
sourced from the environment (populated from `.env` in local development).
Importing this module anywhere gives you the single validated `settings`
instance — no other module should call `os.getenv` directly.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
LOGGING_CONFIG_PATH = ROOT_DIR / "src" / "config" / "logging.yaml"


class Settings(BaseSettings):
    """Application settings loaded from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────
    APP_NAME: str = "Spenza"
    APP_ENV: Literal["dev", "test", "prod"] = "prod"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Server ─────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"  # noqa: S104
    PORT: int = 8000
    WORKERS: int = 1
    LOG_LEVEL: str = "info"
    TIMEOUT: int = 240
    GRACEFUL_TIMEOUT: int = 60

    # ── Database ───────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/spenza"
    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20

    # ── JWT / Auth ─────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = Field(default="change-me-in-production-please")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Cookies ────────────────────────────────────────────────────────
    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"
    COOKIE_DOMAIN: str | None = None
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    COOKIE_PATH: str = "/"

    # ── CORS / Hosts ───────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000"
    TRUSTED_HOSTS: str = "localhost,127.0.0.1"

    # ── Email / SMTP ───────────────────────────────────────────────────
    EMAIL_BACKEND: Literal["console", "smtp"] = "console"
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USE_TLS: bool = True
    SENDER_EMAIL: str | None = None
    SENDER_PASSWORD: str | None = None
    SENDER_NAME: str = "Spenza"

    # ── OTP ────────────────────────────────────────────────────────────
    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    OTP_CLEANUP_INTERVAL_SECONDS: int = 7 * 24 * 3600  # weekly

    # ── Account lockout ────────────────────────────────────────────────
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # ── Password policy ────────────────────────────────────────────────
    PASSWORD_MIN_LENGTH: int = 8

    # ── Rate limiting ──────────────────────────────────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_AUTH: str = "5/minute"
    RATE_LIMIT_OTP: str = "5/minute"

    # ── Logging ────────────────────────────────────────────────────────
    # Unset (None) keeps the per-environment default: rotating files on in
    # dev/test, off in prod (a container's filesystem is ephemeral). Set
    # explicitly to override that default in either direction — e.g.
    # LOG_TO_FILE=true in prod to also write logs/app.log + logs/error.log.
    LOG_TO_FILE: bool | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trusted_hosts_list(self) -> list[str]:
        return [host.strip() for host in self.TRUSTED_HOSTS.split(",") if host.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "prod"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_test(self) -> bool:
        return self.APP_ENV == "test"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings` instance."""
    return Settings()


settings = get_settings()
