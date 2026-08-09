"""Email provider abstraction.

`EmailDeliveryService` (see `notifications.services.email_delivery_service`)
depends only on this interface, never on a concrete provider — swapping SMTP
for Amazon SES/Resend/SendGrid/Mailgun later means writing one new class
here, with no change to retry logic, delivery logging, template rendering,
or any call site.

This is deliberately separate from `src.shared.email` (the OTP/welcome-email
pipeline): that module's `EmailBackend.send()` has no attachment support and
no per-attempt logging, both of which scheduled report delivery needs. Content
here that looks structurally similar to `src.shared.email.backend` is that
interface's superset, not a duplicate of its logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class EmailAttachment:
    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


class BaseEmailProvider(ABC):
    """One email transport. `name` identifies the provider in
    `notification_delivery_logs.provider` for debugging.
    """

    name: ClassVar[str]

    @abstractmethod
    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[EmailAttachment] | None = None,
    ) -> None:
        """Send `html_body` as `subject` to `to`, with optional attachments.

        Raises on failure — callers (`EmailDeliveryService`) are responsible
        for catching, retrying, and logging; a provider itself never retries.
        """
