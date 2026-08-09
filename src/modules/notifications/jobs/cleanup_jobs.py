"""Daily cleanup of stale `notification_delivery_logs` rows.

Reports are generated in memory (`ReportService` never writes a temporary
file — see its module docstring), so there are no temporary report files to
purge; this job's only responsibility is enforcing
`settings.DELIVERY_LOG_RETENTION_DAYS` so that table doesn't grow
unbounded.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.modules.notifications.delivery_log_repository import NotificationDeliveryLogRepository

logger = get_logger(__name__)


async def cleanup_stale_delivery_logs(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.DELIVERY_LOG_RETENTION_DAYS)
    return await NotificationDeliveryLogRepository(session).delete_created_before(cutoff)


async def run_cleanup_job() -> None:
    async with AsyncSessionLocal() as session:
        try:
            deleted = await cleanup_stale_delivery_logs(session)
            await session.commit()
            logger.info("notification_cleanup.completed", deleted=deleted)
        except Exception:
            logger.exception("notification_cleanup.failed")
