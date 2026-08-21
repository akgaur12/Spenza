"""Resend HTTP-API email provider — an alternative to `SMTPProvider` for
hosts (e.g. Render) that block outbound SMTP ports. Same `BaseEmailProvider`
interface, attachments sent as base64 per Resend's API contract.
"""

import base64
import re

import httpx

from src.core.app_config import settings
from src.core.logger import get_logger
from src.modules.notifications.delivery.provider import BaseEmailProvider, EmailAttachment

logger = get_logger(__name__)

_API_URL = "https://api.resend.com/emails"
_TAG_RE = re.compile(r"<[^>]+>")


def _html_to_text(html: str) -> str:
    """Crude plaintext fallback for the multipart alternative a raw-HTML send
    would otherwise lack — templates are our own trusted Jinja output, not
    third-party HTML, so a tag-stripping regex is enough here. A missing
    text/plain part is itself a minor spam-filter signal.
    """
    text = _TAG_RE.sub("", html)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


class ResendProvider(BaseEmailProvider):
    name = "resend"

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "from": f"{settings.SENDER_NAME} <{settings.SENDER_EMAIL}>",
            "to": [to],
            "subject": subject,
            "html": html_body,
            "text": _html_to_text(html_body),
        }
        if attachments:
            payload["attachments"] = [
                {
                    "filename": attachment.filename,
                    "content": base64.b64encode(attachment.content).decode("ascii"),
                }
                for attachment in attachments
            ]

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                json=payload,
            )
            response.raise_for_status()

        logger.info(
            "email.provider.resend.sent",
            to=to,
            subject=subject,
            attachment_count=len(attachments or []),
        )
