"""Data-access layer for notification preferences.

Same rule as every other repository in this codebase: database operations
only, no business logic (in particular, no "what should the default be"
decision — see `preferences.service.NotificationPreferenceService` for
that).
"""

import uuid
from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.notifications.enums import NotificationType
from src.modules.notifications.models import NotificationPreference


class NotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user_and_type(
        self, user_id: uuid.UUID, notification_type: NotificationType
    ) -> NotificationPreference | None:
        result = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.notification_type == notification_type,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[NotificationPreference]:
        result = await self._session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return list(result.scalars().all())

    def create(
        self,
        *,
        user_id: uuid.UUID,
        notification_type: NotificationType,
        enabled: bool,
        in_app_enabled: bool,
        email_enabled: bool,
        delivery_time: time | None,
        timezone: str | None,
    ) -> NotificationPreference:
        preference = NotificationPreference(
            user_id=user_id,
            notification_type=notification_type,
            enabled=enabled,
            in_app_enabled=in_app_enabled,
            email_enabled=email_enabled,
            delivery_time=delivery_time,
            timezone=timezone,
        )
        self._session.add(preference)
        return preference

    async def flush(self) -> None:
        await self._session.flush()
