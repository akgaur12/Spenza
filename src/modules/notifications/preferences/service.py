"""Business logic for notification preferences.

The one rule this module owns: what "no preference row yet" means. A row
is only created the first time a user actually changes something —
`get_for_user`/`list_for_user` synthesize the default for every
`NotificationType` that has none, so the rest of the application (in
particular `NotificationService.send()`) never has to special-case a
missing row itself.
"""

import uuid
from dataclasses import dataclass
from datetime import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.modules.notifications.enums import NotificationType
from src.modules.notifications.models import NotificationPreference
from src.modules.notifications.preferences.repository import NotificationPreferenceRepository

logger = get_logger(__name__)

# The default for any `(user, notification_type)` pair with no explicit
# row: on, shown in-app. Email defaults off for most types (a user has to
# opt in), except the security-sensitive types below, which default to
# emailed too — a user should hear about these even if they've never
# touched their notification preferences.
_DEFAULT_ENABLED = True
_DEFAULT_IN_APP_ENABLED = True
_EMAIL_ENABLED_BY_DEFAULT_TYPES = frozenset({NotificationType.PASSWORD_CHANGED})


def _default_email_enabled(notification_type: NotificationType) -> bool:
    return notification_type in _EMAIL_ENABLED_BY_DEFAULT_TYPES


@dataclass(frozen=True, slots=True)
class ResolvedPreference:
    """A preference with the default already merged in — callers never
    need to know whether it came from a real row or a fallback, except
    `is_default` for display purposes (e.g. a settings UI graying out an
    unmodified row).
    """

    notification_type: NotificationType
    enabled: bool
    in_app_enabled: bool
    email_enabled: bool
    delivery_time: time | None
    timezone: str | None
    is_default: bool


def _resolve(
    notification_type: NotificationType, row: NotificationPreference | None
) -> ResolvedPreference:
    if row is None:
        return ResolvedPreference(
            notification_type=notification_type,
            enabled=_DEFAULT_ENABLED,
            in_app_enabled=_DEFAULT_IN_APP_ENABLED,
            email_enabled=_default_email_enabled(notification_type),
            delivery_time=None,
            timezone=None,
            is_default=True,
        )
    return ResolvedPreference(
        notification_type=row.notification_type,
        enabled=row.enabled,
        in_app_enabled=row.in_app_enabled,
        email_enabled=row.email_enabled,
        delivery_time=row.delivery_time,
        timezone=row.timezone,
        is_default=False,
    )


class NotificationPreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._preferences = NotificationPreferenceRepository(session)

    async def get_for_user(
        self, user_id: uuid.UUID, notification_type: NotificationType
    ) -> ResolvedPreference:
        row = await self._preferences.get_for_user_and_type(user_id, notification_type)
        return _resolve(notification_type, row)

    async def list_for_user(self, user_id: uuid.UUID) -> list[ResolvedPreference]:
        rows_by_type = {
            row.notification_type: row for row in await self._preferences.list_for_user(user_id)
        }
        return [_resolve(t, rows_by_type.get(t)) for t in NotificationType]

    async def update_for_user(
        self, user_id: uuid.UUID, notification_type: NotificationType, updates: dict[str, Any]
    ) -> ResolvedPreference:
        """Upserts: `updates` is a request schema's `model_dump(exclude_
        unset=True)` — only fields the caller actually sent. The first
        change to a given type creates its row, seeded from the default
        for every field this call didn't touch; later changes just update
        the existing row. A field sent as explicit `null` (e.g. clearing a
        previously-set `delivery_time`) is honored, since `exclude_unset`
        already distinguishes "sent as null" from "not sent" upstream.
        """
        row = await self._preferences.get_for_user_and_type(user_id, notification_type)
        if row is None:
            row = self._preferences.create(
                user_id=user_id,
                notification_type=notification_type,
                enabled=updates.get("enabled", _DEFAULT_ENABLED),
                in_app_enabled=updates.get("in_app_enabled", _DEFAULT_IN_APP_ENABLED),
                email_enabled=updates.get(
                    "email_enabled", _default_email_enabled(notification_type)
                ),
                delivery_time=updates.get("delivery_time"),
                timezone=updates.get("timezone"),
            )
        else:
            for field, value in updates.items():
                setattr(row, field, value)

        await self._preferences.flush()
        logger.info(
            "notification_preference.updated",
            user_id=str(user_id),
            notification_type=str(notification_type),
        )
        return _resolve(notification_type, row)
