"""Tests for the daily `notification_delivery_logs` retention cleanup job."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.app_config import settings
from src.modules.notifications.delivery_log_repository import NotificationDeliveryLogRepository
from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus
from src.modules.notifications.jobs.cleanup_jobs import cleanup_stale_delivery_logs
from src.modules.notifications.models import NotificationDeliveryLog


async def test_cleanup_deletes_only_rows_older_than_the_retention_window(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        now = datetime.now(UTC)
        logs = NotificationDeliveryLogRepository(session)
        stale = logs.create(
            notification_id=None,
            channel=DeliveryChannel.EMAIL,
            status=DeliveryLogStatus.SUCCESS,
            attempt=1,
            provider="console",
        )
        fresh = logs.create(
            notification_id=None,
            channel=DeliveryChannel.EMAIL,
            status=DeliveryLogStatus.SUCCESS,
            attempt=1,
            provider="console",
        )
        await logs.flush()
        stale.created_at = now - timedelta(days=settings.DELIVERY_LOG_RETENTION_DAYS + 1)
        fresh.created_at = now - timedelta(days=1)
        await session.commit()

        deleted = await cleanup_stale_delivery_logs(session, now=now)
        await session.commit()

        assert deleted == 1
        remaining = (await session.execute(select(NotificationDeliveryLog))).scalars().all()
        assert [log.id for log in remaining] == [fresh.id]


async def test_cleanup_is_a_no_op_when_nothing_is_stale(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        deleted = await cleanup_stale_delivery_logs(session)
        assert deleted == 0
