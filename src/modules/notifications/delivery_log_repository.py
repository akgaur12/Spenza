"""Data-access layer for `notification_delivery_logs`.

Same rules as `NotificationRepository`: no business logic here, just plain
CRUD/query translation. `EmailDeliveryService` writes one row per delivery
*attempt* through this repository; `core.cleanup` uses it to enforce
`DELIVERY_LOG_RETENTION_DAYS`.
"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus
from src.modules.notifications.models import NotificationDeliveryLog


class NotificationDeliveryLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(
        self,
        *,
        notification_id: uuid.UUID | None,
        channel: DeliveryChannel,
        status: DeliveryLogStatus,
        attempt: int,
        provider: str | None = None,
        error_message: str | None = None,
        sent_at: datetime | None = None,
    ) -> NotificationDeliveryLog:
        log = NotificationDeliveryLog(
            notification_id=notification_id,
            channel=channel,
            status=status,
            attempt=attempt,
            provider=provider,
            error_message=error_message,
            sent_at=sent_at,
        )
        self._session.add(log)
        return log

    async def list_recent(
        self,
        *,
        status: DeliveryLogStatus | None,
        channel: DeliveryChannel | None,
        offset: int,
        limit: int,
    ) -> tuple[list[NotificationDeliveryLog], int]:
        conditions: list[ColumnElement[bool]] = []
        if status is not None:
            conditions.append(NotificationDeliveryLog.status == status)
        if channel is not None:
            conditions.append(NotificationDeliveryLog.channel == channel)

        total = await self._session.scalar(
            select(func.count()).select_from(NotificationDeliveryLog).where(*conditions)
        )
        result = await self._session.execute(
            select(NotificationDeliveryLog)
            .where(*conditions)
            .order_by(NotificationDeliveryLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Bulk-delete stale rows in one statement — never fetch-then-loop,
        since a busy deployment could accumulate many thousands of them.
        """
        result = await self._session.execute(
            delete(NotificationDeliveryLog).where(NotificationDeliveryLog.created_at < cutoff)
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def flush(self) -> None:
        await self._session.flush()
