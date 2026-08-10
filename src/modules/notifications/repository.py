"""Data-access layer for the `notifications` module.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns. `NotificationService` composes these to implement
behavior. Filtering, sorting, pagination, and the read-state bulk update
all happen in SQL; nothing is paginated or looped over in Python.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from src.modules.notifications.enums import (
    DeliveryChannel,
    DeliveryLogStatus,
    NotificationPriority,
    NotificationSortField,
    NotificationType,
    SortOrder,
)
from src.modules.notifications.models import (
    Notification,
    NotificationDeliveryLog,
    NotificationPreference,
)

_SORT_COLUMNS: dict[NotificationSortField, InstrumentedAttribute[Any]] = {
    NotificationSortField.CREATED_AT: Notification.created_at,
    NotificationSortField.PRIORITY: Notification.priority,
}


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: uuid.UUID,
        notification_type: NotificationType,
        title: str,
        message: str,
        payload: dict[str, Any],
        priority: NotificationPriority,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            message=message,
            payload=payload,
            priority=priority,
        )
        self._session.add(notification)
        return notification

    async def get_by_id_for_user(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> Notification | None:
        result = await self._session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        is_read: bool | None = None,
        notification_type: NotificationType | None = None,
        priority: NotificationPriority | None = None,
        sort_by: NotificationSortField = NotificationSortField.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Notification], int]:
        conditions: list[ColumnElement[bool]] = [Notification.user_id == user_id]
        if is_read is not None:
            conditions.append(Notification.is_read == is_read)
        if notification_type is not None:
            conditions.append(Notification.type == notification_type)
        if priority is not None:
            conditions.append(Notification.priority == priority)

        total = await self._session.scalar(
            select(func.count()).select_from(Notification).where(*conditions)
        )

        sort_column = _SORT_COLUMNS[sort_by]
        order = sort_column.asc() if sort_order is SortOrder.ASC else sort_column.desc()

        result = await self._session.execute(
            select(Notification)
            .where(*conditions)
            .order_by(order, Notification.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def unread_count_for_user(self, user_id: uuid.UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        )
        return count or 0

    async def mark_all_read_for_user(self, user_id: uuid.UUID) -> int:
        """A single bulk `UPDATE` — never fetch-then-loop for this, since a
        user could plausibly have thousands of unread rows.
        """
        result = await self._session.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=datetime.now(UTC))
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def delete(self, notification: Notification) -> None:
        await self._session.delete(notification)

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Bulk-delete stale rows in one statement — never fetch-then-loop,
        since a busy deployment could accumulate many thousands of them.
        Used by `core.cleanup` to enforce `NOTIFICATION_RETENTION_DAYS`
        regardless of read state.
        """
        result = await self._session.execute(
            delete(Notification).where(Notification.created_at < cutoff)
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def flush(self) -> None:
        await self._session.flush()

    async def list_pending_email_deliveries(
        self, *, max_attempts: int, limit: int = 500
    ) -> list[Notification]:
        """Notifications whose owner has email enabled for that type (a
        default/missing preference row means email is off, so this only
        ever matches an explicit opt-in row) and which have neither
        succeeded nor exhausted `max_attempts` failed attempts yet.

        This is a safety-net sweep, not the primary delivery path —
        `EmailChannel` already attempts (and retries) delivery inline
        inside `NotificationService.send()`. By the time that returns, a
        notification's email is already `SUCCESS` or exhausted-`FAILED` in
        `notification_delivery_logs`; this only ever matches the rare case
        where the process died before that resolved either way. See
        `notifications.jobs.notification_jobs`.
        """
        successful_ids = select(NotificationDeliveryLog.notification_id).where(
            NotificationDeliveryLog.channel == DeliveryChannel.EMAIL,
            NotificationDeliveryLog.status == DeliveryLogStatus.SUCCESS,
        )
        attempt_counts = (
            select(
                NotificationDeliveryLog.notification_id.label("notification_id"),
                func.count().label("attempts"),
            )
            .where(NotificationDeliveryLog.channel == DeliveryChannel.EMAIL)
            .group_by(NotificationDeliveryLog.notification_id)
            .subquery()
        )
        result = await self._session.execute(
            select(Notification)
            .join(
                NotificationPreference,
                (NotificationPreference.user_id == Notification.user_id)
                & (NotificationPreference.notification_type == Notification.type),
            )
            .outerjoin(attempt_counts, attempt_counts.c.notification_id == Notification.id)
            .where(
                NotificationPreference.enabled.is_(True),
                NotificationPreference.email_enabled.is_(True),
                Notification.id.not_in(successful_ids),
                func.coalesce(attempt_counts.c.attempts, 0) < max_attempts,
            )
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
