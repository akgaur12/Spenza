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

# `ai_assistant.enums` has no dependency on `src.core` (a dependency-free
# leaf module, like every other module's `enums.py`), so importing it here
# to type `AI_DEFAULT_PROVIDER` cannot create an import cycle — deliberate,
# so the DB column type and the settings default share one enum instead of
# a settings-level `Literal` that could drift from it.
from src.modules.ai_assistant.enums import LLMProvider

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
    # There is no per-user timezone preference yet, so every user's
    # "today"/"this week"/"this month"/"this year" boundaries (e.g. in the
    # dashboard) are computed in this single application-wide zone.
    APP_TIMEZONE: str = "Asia/Kolkata"

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
    # "resend"/"mailjet" send over an HTTP API instead of raw SMTP — needed
    # on hosts (e.g. Render) that block outbound SMTP ports.
    # Each backend has its own sender address since each requires its sender
    # domain/mailbox to be independently verified with that provider — e.g.
    # SMTP_SENDER_EMAIL might be a Gmail address while RESEND_SENDER_EMAIL is
    # on a domain verified in the Resend dashboard.
    EMAIL_BACKEND: Literal["console", "smtp", "resend", "mailjet"] = "console"
    SMTP_SERVER: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USE_TLS: bool = True
    SMTP_SENDER_EMAIL: str | None = None
    SENDER_PASSWORD: str | None = None
    SENDER_NAME: str = "Spenza"
    RESEND_API_KEY: str | None = None
    RESEND_SENDER_EMAIL: str | None = None
    MAILJET_API_KEY: str | None = None
    MAILJET_API_SECRET: str | None = None
    MAILJET_SENDER_EMAIL: str | None = None

    # ── OTP ────────────────────────────────────────────────────────────
    OTP_LENGTH: int = 6
    OTP_EXPIRE_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60

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

    # ── Import / Export ────────────────────────────────────────────────
    MAX_IMPORT_FILE_SIZE_BYTES: int = 10 * 1024 * 1024
    MAX_IMPORT_ROWS: int = 10_000
    IMPORT_SESSION_EXPIRE_MINUTES: int = 30
    MAX_EXPORT_ROWS: int = 50_000

    # ── Recurring expenses ─────────────────────────────────────────────
    # The daily due-recurrence job runs once per day at this time, in
    # `APP_TIMEZONE` — see `recurring_expenses.scheduler`.
    RECURRING_EXPENSE_SCHEDULER_HOUR: int = 1
    RECURRING_EXPENSE_SCHEDULER_MINUTE: int = 0

    # ── Scheduled email delivery (notifications) ────────────────────────
    # Retry/backoff for a single email send — see `EmailDeliveryService`.
    # Attempt N sleeps `EMAIL_RETRY_BASE_DELAY_SECONDS * 2**(N-1)` before
    # the next try; after `EMAIL_MAX_RETRIES` failures delivery is logged
    # as failed and abandoned rather than blocking future notifications.
    EMAIL_MAX_RETRIES: int = 3
    EMAIL_RETRY_BASE_DELAY_SECONDS: float = 2.0
    # How often the safety-net sweep re-attempts any notification email
    # that never resolved to SUCCESS or exhausted FAILED — see
    # `notifications.jobs.notification_jobs`.
    NOTIFICATION_EMAIL_JOB_INTERVAL_MINUTES: int = 360
    # The monthly/yearly report jobs run once a day (in `APP_TIMEZONE`) and
    # only actually generate/send a report on the configured day (and, for
    # yearly, month) — see `notifications.jobs.report_jobs`.
    MONTHLY_REPORT_SCHEDULER_HOUR: int = 6
    MONTHLY_REPORT_SCHEDULER_MINUTE: int = 0
    MONTHLY_REPORT_DELIVERY_DAY: int = 1
    YEARLY_REPORT_SCHEDULER_HOUR: int = 6
    YEARLY_REPORT_SCHEDULER_MINUTE: int = 30
    YEARLY_REPORT_DELIVERY_DAY: int = 1
    YEARLY_REPORT_DELIVERY_MONTH: int = 1
    # ── Data retention / cleanup ──────────────────────────────────────────
    # A single daily job (`src.core.cleanup.run_cleanup_job`, scheduled by
    # `notifications.scheduler` at the hour/minute below) purges every table
    # in this section so none of them grow unbounded. `email_otps` is the
    # one exception: its retention math is a special case (see
    # `users.service.cleanup_expired_otps`), so it has no `_RETENTION_DAYS`
    # setting of its own.
    NOTIFICATION_CLEANUP_SCHEDULER_HOUR: int = 3
    NOTIFICATION_CLEANUP_SCHEDULER_MINUTE: int = 0
    # `notification_delivery_logs` rows older than this are purged daily.
    DELIVERY_LOG_RETENTION_DAYS: int = 90
    # `notifications` rows (read or unread) older than this are purged daily.
    NOTIFICATION_RETENTION_DAYS: int = 60
    # `import_sessions` rows are already unusable `IMPORT_SESSION_EXPIRE_MINUTES`
    # after creation; this is how much longer they're kept around (for
    # support/debugging) before being purged.
    IMPORT_SESSION_RETENTION_DAYS: int = 2
    # `refresh_sessions` rows are purged this many days after they're
    # revoked or past `expires_at` — active, valid sessions are never
    # touched regardless of age.
    REFRESH_SESSION_RETENTION_DAYS: int = 30
    # `users` rows that never completed signup OTP verification are purged
    # this many days after creation — long enough for a real user to come
    # back and verify, short enough to free up a squatted username/email.
    # A verified account is never touched regardless of age.
    USER_UNVERIFIED_RETENTION_DAYS: int = 7

    # ── AI Assistant ───────────────────────────────────────────────────
    AI_DEFAULT_PROVIDER: LLMProvider = LLMProvider.OLLAMA
    AI_DEFAULT_MODEL: str = "llama3.1:8b"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    AWS_BEDROCK_REGION: str | None = None
    AWS_BEDROCK_ACCESS_KEY_ID: str | None = None
    AWS_BEDROCK_SECRET_ACCESS_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    NVIDIA_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    HUGGINGFACE_API_KEY: str | None = None
    OPEN_ROUTER_API_KEY: str | None = None
    # Wall-clock budgets so a slow/unreachable provider or tool can never
    # hang a request indefinitely — see `agent.runner.AgentRunner`.
    AI_LLM_TIMEOUT_SECONDS: float = 30.0
    AI_TOOL_TIMEOUT_SECONDS: float = 15.0
    AI_AGENT_TIMEOUT_SECONDS: float = 90.0
    # How many of a chat's most recent messages are loaded into the agent's
    # context window — a flat cutoff for now; see `ChatMessageRepository.
    # list_recent_for_context` for where summarization/long-term memory
    # would plug in later without a schema change.
    AI_CONTEXT_WINDOW_MESSAGES: int = 30
    AI_CHAT_REQUESTS_PER_MINUTE: str = "10/minute"
    AI_TITLE_GENERATION_ENABLED: bool = True

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
    def active_sender_email(self) -> str | None:
        """The sender address for whichever backend `EMAIL_BACKEND` selects —
        each backend has its own, since each requires independent domain
        verification with that provider.
        """
        return {
            "smtp": self.SMTP_SENDER_EMAIL,
            "resend": self.RESEND_SENDER_EMAIL,
            "mailjet": self.MAILJET_SENDER_EMAIL,
        }.get(self.EMAIL_BACKEND)

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
