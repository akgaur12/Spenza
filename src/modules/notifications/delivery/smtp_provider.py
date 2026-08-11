"""SMTP email provider — sends via `aiosmtplib`, same STARTTLS pattern as
`src.shared.email.backend.SMTPEmailBackend`, extended with attachment
support (needed for report PDFs) that the OTP pipeline never required.

`ConsoleEmailProvider` mirrors `ConsoleEmailBackend`: it never touches the
network, logging what would have been sent instead — the default whenever
`EMAIL_BACKEND` isn't explicitly set to `smtp`, so local development and the
test suite never send a real email through this module either.
"""

from email.message import EmailMessage

import aiosmtplib

from src.core.app_config import settings
from src.core.logger import get_logger
from src.modules.notifications.delivery.provider import BaseEmailProvider, EmailAttachment
from src.modules.notifications.delivery.resend_provider import ResendProvider

logger = get_logger(__name__)


class ConsoleEmailProvider(BaseEmailProvider):
    name = "console"

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        logger.info(
            "email.provider.console",
            to=to,
            subject=subject,
            attachment_count=len(attachments or []),
            body_preview=html_body[:200],
        )


class SMTPProvider(BaseEmailProvider):
    name = "smtp"

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        message = EmailMessage()
        message["From"] = f"{settings.SENDER_NAME} <{settings.SENDER_EMAIL}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content("This email requires an HTML-capable client.")
        message.add_alternative(html_body, subtype="html")

        for attachment in attachments or []:
            maintype, _, subtype = attachment.mime_type.partition("/")
            message.add_attachment(
                attachment.content,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.filename,
            )

        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_SERVER,
            port=settings.SMTP_PORT,
            start_tls=settings.SMTP_USE_TLS,
            username=settings.SENDER_EMAIL,
            password=settings.SENDER_PASSWORD,
        )
        logger.info(
            "email.provider.smtp.sent",
            to=to,
            subject=subject,
            attachment_count=len(attachments or []),
        )


def get_email_provider() -> BaseEmailProvider:
    """Select the configured provider — same `EMAIL_BACKEND` setting
    `src.shared.email.backend.get_email_backend` reads, so one environment
    variable controls both pipelines' safety in dev/test.
    """
    if settings.EMAIL_BACKEND == "smtp":
        return SMTPProvider()
    if settings.EMAIL_BACKEND == "resend":
        return ResendProvider()
    return ConsoleEmailProvider()
