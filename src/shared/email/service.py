"""High-level, template-rendering email API used by feature modules.

Feature services call these named methods (`send_signup_otp`, etc.) instead of
touching Jinja2 or the SMTP client directly, so template changes never ripple
into business logic.
"""

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.core.app_config import settings
from src.shared.email.backend import EmailBackend, get_email_backend

TEMPLATES_DIR = Path(__file__).parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)


class EmailService:
    """Renders reusable HTML templates and dispatches them via an `EmailBackend`."""

    def __init__(self, backend: EmailBackend | None = None) -> None:
        self._backend = backend or get_email_backend()

    def _render(self, template_name: str, **context: object) -> str:
        template = _jinja_env.get_template(template_name)
        return template.render(current_year=datetime.now(UTC).year, **context)

    async def send_signup_otp(self, *, to: str, username: str, otp: str) -> None:
        html = self._render(
            "signup_otp.html",
            username=username,
            otp=otp,
            expires_in_minutes=settings.OTP_EXPIRE_MINUTES,
        )
        await self._backend.send(to=to, subject="Verify your Spenza account", html_body=html)

    async def send_password_reset_otp(self, *, to: str, username: str, otp: str) -> None:
        html = self._render(
            "reset_otp.html",
            username=username,
            otp=otp,
            expires_in_minutes=settings.OTP_EXPIRE_MINUTES,
        )
        await self._backend.send(to=to, subject="Reset your Spenza password", html_body=html)

    async def send_welcome_email(self, *, to: str, username: str) -> None:
        html = self._render("welcome.html", username=username)
        await self._backend.send(to=to, subject="Welcome to Spenza", html_body=html)


@lru_cache
def get_email_service() -> EmailService:
    """Return the process-wide cached `EmailService` (backend fixed at startup)."""
    return EmailService()
