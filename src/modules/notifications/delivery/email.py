"""Email delivery — completed in Phase 11B.

Responsibilities, and only these: look up the recipient, pick and render a
template, and hand off to `EmailDeliveryService` (which owns retry/backoff
and `notification_delivery_logs`). It does not generate reports and does
not query business data beyond the `User` row it needs for an address —
scheduled report emails (with their PDF attachment) are sent directly by
`notifications.jobs.report_jobs`, not through this channel, so they never
duplicate as a second plain-text notification email.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.modules.notifications.delivery.base import BaseNotificationChannel
from src.modules.notifications.delivery.provider import BaseEmailProvider
from src.modules.notifications.delivery.templates import render_template
from src.modules.notifications.enums import NotificationType
from src.modules.notifications.models import Notification
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.users.repository import UserRepository

logger = get_logger(__name__)

_RECURRING_EXPENSE_TEMPLATE = "recurring_expense.html"
_GENERIC_TEMPLATE = "generic_notification.html"


class EmailChannel(BaseNotificationChannel):
    def __init__(self, session: AsyncSession, provider: BaseEmailProvider | None = None) -> None:
        self._users = UserRepository(session)
        self._delivery = EmailDeliveryService(session, provider)

    async def send(self, notification: Notification) -> None:
        if notification.type is NotificationType.REPORT_READY:
            # The report itself — with its PDF attached — was already
            # emailed directly by the report job / `send-now` endpoint
            # before this notification even existed (see
            # `jobs.report_jobs.build_report_email`). A second,
            # attachment-less "your report is ready" email here would just
            # be a redundant duplicate of the same event.
            logger.info(
                "notification.channel.skipped",
                channel="email",
                notification_id=str(notification.id),
                reason="report_email_already_sent_by_report_job",
            )
            return

        user = await self._users.get_by_id(notification.user_id)
        if user is None:
            logger.warning(
                "notification.channel.skipped",
                channel="email",
                notification_id=str(notification.id),
                reason="user_not_found",
            )
            return

        template_name = (
            _RECURRING_EXPENSE_TEMPLATE
            if notification.type is NotificationType.RECURRING_EXPENSE_CREATED
            else _GENERIC_TEMPLATE
        )
        html_body = render_template(
            template_name,
            username=user.full_name or user.username,
            title=notification.title,
            message=notification.message,
            payload=notification.payload,
        )
        await self._delivery.send(
            to=user.email,
            subject=f"Spenza: {notification.title}",
            html_body=html_body,
            notification_id=notification.id,
        )
