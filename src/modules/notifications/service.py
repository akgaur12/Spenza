"""Business logic for the `notifications` module.

`NotificationService.send()` is the single entry point every other module
in Spenza uses to notify a user — never a direct `Notification(...)`
insert, never a direct email send. It owns the three decisions described
in the module's design: which channels are enabled (via
`NotificationPreferenceService`), how the notification is persisted (via
`NotificationRepository`), and how it's delivered (via the
`BaseNotificationChannel` registry in `delivery/`). A caller only ever
supplies *what* happened, never *how* it reaches the user.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.modules.notifications.delivery.base import BaseNotificationChannel
from src.modules.notifications.delivery.email import EmailChannel
from src.modules.notifications.delivery.in_app import InAppChannel
from src.modules.notifications.enums import (
    DeliveryChannel,
    NotificationPriority,
    NotificationSortField,
    NotificationType,
    SortOrder,
)
from src.modules.notifications.exceptions import NotificationNotFoundError
from src.modules.notifications.models import Notification
from src.modules.notifications.preferences.service import NotificationPreferenceService
from src.modules.notifications.repository import NotificationRepository

logger = get_logger(__name__)


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._notifications = NotificationRepository(session)
        self._preferences = NotificationPreferenceService(session)
        self._channels: dict[DeliveryChannel, BaseNotificationChannel] = {
            DeliveryChannel.IN_APP: InAppChannel(),
            DeliveryChannel.EMAIL: EmailChannel(session),
        }

    async def send(
        self,
        *,
        user_id: uuid.UUID,
        type: NotificationType,  # noqa: A002 — matches every caller's `type=NotificationType.X`
        title: str,
        message: str,
        payload: dict[str, Any] | None = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
    ) -> Notification | None:
        """Create and deliver one notification, or do nothing at all if
        the user has this `type` disabled entirely. Returns `None` in that
        case — every other module's call site can treat the return value
        as "did anything happen", without needing its own preference check.
        """
        preference = await self._preferences.get_for_user(user_id, type)
        if not preference.enabled:
            logger.info(
                "notification.skipped",
                user_id=str(user_id),
                notification_type=str(type),
                reason="disabled_by_preference",
            )
            return None

        notification = self._notifications.create(
            user_id=user_id,
            notification_type=type,
            title=title,
            message=message,
            payload=payload or {},
            priority=priority,
        )
        await self._notifications.flush()
        logger.info(
            "notification.created",
            notification_id=str(notification.id),
            user_id=str(user_id),
            notification_type=str(type),
            priority=str(priority),
        )

        if preference.in_app_enabled:
            await self._channels[DeliveryChannel.IN_APP].send(notification)
        if preference.email_enabled:
            await self._channels[DeliveryChannel.EMAIL].send(notification)

        return notification

    async def get_for_user(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification:
        notification = await self._notifications.get_by_id_for_user(notification_id, user_id)
        if notification is None:
            raise NotificationNotFoundError()
        return notification

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        is_read: bool | None,
        notification_type: NotificationType | None,
        priority: NotificationPriority | None,
        sort_by: NotificationSortField,
        sort_order: SortOrder,
        page: int,
        page_size: int,
    ) -> tuple[list[Notification], int]:
        offset = (page - 1) * page_size
        return await self._notifications.list_for_user(
            user_id,
            is_read=is_read,
            notification_type=notification_type,
            priority=priority,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=offset,
            limit=page_size,
        )

    async def unread_count_for_user(self, user_id: uuid.UUID) -> int:
        return await self._notifications.unread_count_for_user(user_id)

    async def mark_read_for_user(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> Notification:
        notification = await self.get_for_user(notification_id, user_id)
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = datetime.now(UTC)
            await self._notifications.flush()
            logger.info(
                "notification.read", notification_id=str(notification_id), user_id=str(user_id)
            )
        return notification

    async def mark_all_read_for_user(self, user_id: uuid.UUID) -> int:
        updated = await self._notifications.mark_all_read_for_user(user_id)
        await self._notifications.flush()
        logger.info("notification.mark_all_read", user_id=str(user_id), updated=updated)
        return updated

    async def delete_for_user(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> None:
        notification = await self.get_for_user(notification_id, user_id)
        await self._notifications.delete(notification)
        await self._notifications.flush()
        logger.info(
            "notification.deleted", notification_id=str(notification_id), user_id=str(user_id)
        )
