"""Retry/backoff + delivery-logging engine shared by every Phase 11B email
send — a notification email, a scheduled report, or a test email all go
through `EmailDeliveryService.send()`, so retry behavior and
`notification_delivery_logs` bookkeeping is identical everywhere rather
than reimplemented per caller.

`send()` never raises: a provider failure is retried up to
`settings.EMAIL_MAX_RETRIES` times with exponential backoff, then logged
and abandoned (see the module-level "Retry Strategy" / "Do not block future
deliveries" requirement) — callers get a plain `bool` back instead.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.logger import get_logger
from src.modules.notifications.delivery.provider import BaseEmailProvider, EmailAttachment
from src.modules.notifications.delivery.smtp_provider import get_email_provider
from src.modules.notifications.delivery_log_repository import NotificationDeliveryLogRepository
from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus

logger = get_logger(__name__)


class EmailDeliveryService:
    def __init__(
        self,
        session: AsyncSession,
        provider: BaseEmailProvider | None = None,
        *,
        max_retries: int | None = None,
        retry_base_delay_seconds: float | None = None,
    ) -> None:
        self._logs = NotificationDeliveryLogRepository(session)
        self._provider = provider or get_email_provider()
        self._max_retries = max_retries if max_retries is not None else settings.EMAIL_MAX_RETRIES
        self._retry_base_delay = (
            retry_base_delay_seconds
            if retry_base_delay_seconds is not None
            else settings.EMAIL_RETRY_BASE_DELAY_SECONDS
        )

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html_body: str,
        attachments: list[EmailAttachment] | None = None,
        notification_id: uuid.UUID | None = None,
    ) -> bool:
        """Attempt delivery, retrying on failure. Returns whether it
        eventually succeeded; every attempt (success or failure) gets its
        own `notification_delivery_logs` row.
        """
        for attempt in range(1, self._max_retries + 1):
            try:
                await self._provider.send_email(
                    to=to, subject=subject, html_body=html_body, attachments=attachments
                )
            except Exception as exc:
                self._logs.create(
                    notification_id=notification_id,
                    channel=DeliveryChannel.EMAIL,
                    status=DeliveryLogStatus.FAILED,
                    attempt=attempt,
                    provider=self._provider.name,
                    error_message=str(exc)[:2000],
                )
                await self._logs.flush()
                logger.warning(
                    "email.delivery.attempt_failed",
                    to=to,
                    attempt=attempt,
                    notification_id=str(notification_id) if notification_id else None,
                    error=str(exc),
                )
                if attempt < self._max_retries:
                    logger.info(
                        "email.delivery.retry_scheduled",
                        to=to,
                        next_attempt=attempt + 1,
                        delay_seconds=self._retry_base_delay * (2 ** (attempt - 1)),
                    )
                    await asyncio.sleep(self._retry_base_delay * (2 ** (attempt - 1)))
                    continue
                logger.error(
                    "email.delivery.retries_exhausted",
                    to=to,
                    notification_id=str(notification_id) if notification_id else None,
                    attempts=attempt,
                )
                return False
            else:
                self._logs.create(
                    notification_id=notification_id,
                    channel=DeliveryChannel.EMAIL,
                    status=DeliveryLogStatus.SUCCESS,
                    attempt=attempt,
                    provider=self._provider.name,
                    sent_at=datetime.now(UTC),
                )
                await self._logs.flush()
                logger.info(
                    "email.delivery.sent",
                    to=to,
                    attempt=attempt,
                    notification_id=str(notification_id) if notification_id else None,
                )
                return True
        return False  # pragma: no cover — unreachable, the loop always returns
