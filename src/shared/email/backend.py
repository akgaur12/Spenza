"""Pluggable email delivery backends.

`ConsoleEmailBackend` logs the rendered email instead of sending it — used
for local development and the test suite so nothing ever touches a real
SMTP server unless `EMAIL_BACKEND=smtp` is explicitly configured.
"""

import re
from abc import ABC, abstractmethod
from email.message import EmailMessage

import aiosmtplib
import httpx

from src.core.app_config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

_OTP_MARKER_RE = re.compile(r"<!-- OTP:(\d+) -->")
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    """Crude plaintext fallback for the multipart alternative a raw-HTML send
    would otherwise lack — templates are our own trusted Jinja output, not
    third-party HTML, so a tag-stripping regex is enough here. A missing
    text/plain part is itself a minor spam-filter signal.
    """
    text = _TAG_RE.sub("", html)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class EmailBackend(ABC):
    """Strategy interface for sending an already-rendered HTML email."""

    @abstractmethod
    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        """Send `html_body` as `subject` to `to`."""


class ConsoleEmailBackend(EmailBackend):
    """Logs the email instead of delivering it (dev / test environments).

    OTP emails carry a hidden `<!-- OTP:123456 -->` marker (invisible to real
    mail clients) so the code can be read straight from the log during local
    testing, without needing a real inbox.
    """

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        otp_match = _OTP_MARKER_RE.search(html_body)
        logger.info(
            "email.sent.console",
            to=to,
            subject=subject,
            otp=otp_match.group(1) if otp_match else None,
            body_preview=html_body[:200],
        )


class SMTPEmailBackend(EmailBackend):
    """Delivers email via SMTP (Gmail by default) using STARTTLS."""

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        message = EmailMessage()
        message["From"] = f"{settings.SENDER_NAME} <{settings.SENDER_EMAIL}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content("This email requires an HTML-capable client.")
        message.add_alternative(html_body, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_SERVER,
            port=settings.SMTP_PORT,
            start_tls=settings.SMTP_USE_TLS,
            username=settings.SENDER_EMAIL,
            password=settings.SENDER_PASSWORD,
        )
        logger.info("email.sent.smtp", to=to, subject=subject)


class ResendEmailBackend(EmailBackend):
    """Delivers email via the Resend HTTP API.

    Goes over HTTPS rather than an SMTP port, so it works on hosts (e.g.
    Render) that block outbound SMTP traffic.
    """

    _API_URL = "https://api.resend.com/emails"

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self._API_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json={
                    "from": f"{settings.SENDER_NAME} <{settings.SENDER_EMAIL}>",
                    "to": [to],
                    "subject": subject,
                    "html": html_body,
                    "text": _html_to_text(html_body),
                },
            )
            response.raise_for_status()
        logger.info("email.sent.resend", to=to, subject=subject)


def get_email_backend() -> EmailBackend:
    """Select the configured backend (`console`, `smtp`, or `resend`)."""
    if settings.EMAIL_BACKEND == "smtp":
        return SMTPEmailBackend()
    if settings.EMAIL_BACKEND == "resend":
        return ResendEmailBackend()
    return ConsoleEmailBackend()
