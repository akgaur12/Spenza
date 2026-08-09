"""Hourly safety-net sweep for notification email delivery.

`EmailChannel` already attempts (and retries) email delivery synchronously
inside `NotificationService.send()` — by the time that call returns, a
notification's email is already `SUCCESS` or exhausted-`FAILED` in
`notification_delivery_logs`. This job exists for the one case that inline
path can't cover: the process died mid-attempt (killed, OOM, deploy) before
any delivery log row was written, or before an in-flight retry finished, so
the notification never resolved either way. Running on
`NOTIFICATION_EMAIL_JOB_INTERVAL_MINUTES`, it re-attempts anything that
still isn't `SUCCESS` and hasn't yet burned through `EMAIL_MAX_RETRIES`
attempts — see `NotificationRepository.list_pending_email_deliveries`.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.modules.notifications.delivery.email import EmailChannel
from src.modules.notifications.repository import NotificationRepository

logger = get_logger(__name__)

_SWEEP_BATCH_LIMIT = 500


@dataclass(frozen=True, slots=True)
class NotificationEmailJobSummary:
    checked: int


async def process_pending_notification_emails(session: AsyncSession) -> NotificationEmailJobSummary:
    notifications = NotificationRepository(session)
    pending = await notifications.list_pending_email_deliveries(
        max_attempts=settings.EMAIL_MAX_RETRIES, limit=_SWEEP_BATCH_LIMIT
    )
    channel = EmailChannel(session)
    for notification in pending:
        try:
            await channel.send(notification)
        except Exception:
            logger.exception(
                "notification_email_job.item_failed", notification_id=str(notification.id)
            )
            await session.rollback()
            continue
        await session.commit()
    return NotificationEmailJobSummary(checked=len(pending))


async def run_notification_email_job() -> None:
    async with AsyncSessionLocal() as session:
        try:
            summary = await process_pending_notification_emails(session)
            logger.info("notification_email_job.completed", checked=summary.checked)
        except Exception:
            logger.exception("notification_email_job.failed")
