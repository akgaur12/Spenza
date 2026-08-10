"""Unified daily housekeeping: purges stale rows across modules so no table
grows unbounded.

One mechanism for everything: a single APScheduler job
(`notifications.scheduler`, id `maintenance.cleanup`) calls `run_cleanup_job`
once a day. Each table's purge runs in its own short-lived session/
transaction, so one table's failure can never block another's. Adding a new
table's cleanup means adding one `_TASKS` entry — not a new job or scheduler.

`email_otps` is the one exception: it keeps its own function
(`users.service.cleanup_expired_otps`) and advisory lock, since its
retention math (double the OTP's own expiry window, to protect a still-
redeemable `reset_token`) doesn't fit the plain `now - retention_days`
pattern the rest of these follow.

`unverified_users` purges `User` rows that never completed signup OTP
verification — this also frees up any username/email they were squatting,
since only a *verified* account blocks reuse at signup (see
`UserService.signup`).
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.modules.import_export.import_repository import ImportSessionRepository
from src.modules.notifications.delivery_log_repository import NotificationDeliveryLogRepository
from src.modules.notifications.repository import NotificationRepository
from src.modules.users.repository import RefreshSessionRepository, UserRepository
from src.modules.users.service import cleanup_expired_otps

logger = get_logger(__name__)


class _PurgeFn(Protocol):
    async def __call__(self, session: AsyncSession, *, now: datetime | None = None) -> int: ...


async def purge_delivery_logs(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.DELIVERY_LOG_RETENTION_DAYS)
    return await NotificationDeliveryLogRepository(session).delete_older_than(cutoff)


async def purge_notifications(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS)
    return await NotificationRepository(session).delete_older_than(cutoff)


async def purge_import_sessions(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.IMPORT_SESSION_RETENTION_DAYS)
    return await ImportSessionRepository(session).delete_older_than(cutoff)


async def purge_refresh_sessions(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.REFRESH_SESSION_RETENTION_DAYS)
    return await RefreshSessionRepository(session).delete_older_than(cutoff)


async def purge_unverified_users(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=settings.USER_UNVERIFIED_RETENTION_DAYS)
    return await UserRepository(session).delete_unverified_older_than(cutoff)


_TASKS: dict[str, _PurgeFn] = {
    "notification_delivery_logs": purge_delivery_logs,
    "notifications": purge_notifications,
    "import_sessions": purge_import_sessions,
    "refresh_sessions": purge_refresh_sessions,
    "unverified_users": purge_unverified_users,
}


async def run_cleanup_job() -> None:
    """Run every registered purge, each in its own session/transaction, and
    log the row count deleted per table. A failure in one table is logged
    and skipped rather than aborting the rest.
    """
    try:
        async with AsyncSessionLocal() as session:
            deleted = await cleanup_expired_otps(session)
        logger.info("cleanup.completed", table="email_otps", deleted=deleted)
    except Exception:
        logger.exception("cleanup.failed", table="email_otps")

    now = datetime.now(UTC)
    for table, purge in _TASKS.items():
        try:
            async with AsyncSessionLocal() as session:
                deleted = await purge(session, now=now)
                await session.commit()
            logger.info("cleanup.completed", table=table, deleted=deleted)
        except Exception:
            logger.exception("cleanup.failed", table=table)
