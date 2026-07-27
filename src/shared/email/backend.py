"""Pluggable email delivery backends.

`ConsoleEmailBackend` logs the rendered email instead of sending it — used
for local development and the test suite so nothing ever touches a real
SMTP server unless `EMAIL_BACKEND=smtp` is explicitly configured.
"""

import re
from abc import ABC, abstractmethod
from email.message import EmailMessage

import aiosmtplib

from src.core.app_config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

_OTP_MARKER_RE = re.compile(r"<!-- OTP:(\d+) -->")


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


def get_email_backend() -> EmailBackend:
    """Select the configured backend (`console` or `smtp`)."""
    if settings.EMAIL_BACKEND == "smtp":
        return SMTPEmailBackend()
    return ConsoleEmailBackend()
