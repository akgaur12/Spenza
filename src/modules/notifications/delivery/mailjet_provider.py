"""Mailjet Send API v3.1 email provider — an alternative to `SMTPProvider`
for hosts (e.g. Render) that block outbound SMTP ports. Same
`BaseEmailProvider` interface, attachments sent as base64 per Mailjet's
v3.1 API contract.
"""

import base64
import re

import httpx

from src.core.app_config import settings
from src.core.logger import get_logger
from src.modules.notifications.delivery.provider import BaseEmailProvider, EmailAttachment

logger = get_logger(__name__)

_API_URL = "https://api.mailjet.com/v3.1/send"
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    """Crude plaintext fallback for the multipart alternative a raw-HTML send
    would otherwise lack — templates are our own trusted Jinja output, not
    third-party HTML, so a tag-stripping regex is enough here. A missing
    text/plain part is itself a minor spam-filter signal.
    """
    text = _TAG_RE.sub("", html)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class MailjetProvider(BaseEmailProvider):
    name = "mailjet"

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        message: dict[str, object] = {
            "From": {"Email": settings.MAILJET_SENDER_EMAIL, "Name": settings.SENDER_NAME},
            "To": [{"Email": to}],
            "Subject": subject,
            "HTMLPart": html_body,
            "TextPart": _html_to_text(html_body),
        }
        if attachments:
            message["Attachments"] = [
                {
                    "ContentType": attachment.mime_type,
                    "Filename": attachment.filename,
                    "Base64Content": base64.b64encode(attachment.content).decode("ascii"),
                }
                for attachment in attachments
            ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _API_URL,
                auth=(settings.MAILJET_API_KEY or "", settings.MAILJET_API_SECRET or ""),
                json={"Messages": [message]},
            )
            response.raise_for_status()

        logger.info(
            "email.provider.mailjet.sent",
            to=to,
            subject=subject,
            attachment_count=len(attachments or []),
        )
