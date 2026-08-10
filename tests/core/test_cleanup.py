"""Tests for the unified daily housekeeping sweep in `src.core.cleanup`.

Only the individual `purge_*` functions are tested directly against the
per-test SQLite database — `run_cleanup_job` itself opens sessions via the
module-level `AsyncSessionLocal` bound to the real `DATABASE_URL` (see
`tests/notifications/test_scheduler.py`'s docstring for why job wrappers
follow this pattern), so it isn't exercised end-to-end here.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.app_config import settings
from src.core.cleanup import (
    purge_delivery_logs,
    purge_import_sessions,
    purge_notifications,
    purge_refresh_sessions,
    purge_unverified_users,
)
from src.modules.import_export.models import ImportSession, ImportSessionStatus
from src.modules.notifications.delivery_log_repository import NotificationDeliveryLogRepository
from src.modules.notifications.enums import (
    DeliveryChannel,
    DeliveryLogStatus,
    NotificationPriority,
    NotificationType,
)
from src.modules.notifications.models import Notification, NotificationDeliveryLog
from src.modules.users.models import RefreshSession, User


async def _make_user(session: AsyncSession, *, email: str) -> User:
    user = User(email=email, username=email.split("@")[0], password_hash="x")
    session.add(user)
    await session.flush()
    return user


async def test_purge_delivery_logs_deletes_only_rows_older_than_retention(
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

        deleted = await purge_delivery_logs(session, now=now)
        await session.commit()

        assert deleted == 1
        remaining = (await session.execute(select(NotificationDeliveryLog))).scalars().all()
        assert [log.id for log in remaining] == [fresh.id]


async def test_purge_delivery_logs_is_a_no_op_when_nothing_is_stale(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        deleted = await purge_delivery_logs(session)
        assert deleted == 0


async def test_purge_notifications_deletes_only_rows_older_than_retention(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, email="notif-cleanup@example.com")
        now = datetime.now(UTC)
        stale = Notification(
            user_id=user.id,
            type=NotificationType.PASSWORD_CHANGED,
            title="t",
            message="m",
            payload={},
            priority=NotificationPriority.NORMAL,
            created_at=now - timedelta(days=settings.NOTIFICATION_RETENTION_DAYS + 1),
        )
        fresh = Notification(
            user_id=user.id,
            type=NotificationType.PASSWORD_CHANGED,
            title="t",
            message="m",
            payload={},
            priority=NotificationPriority.NORMAL,
            created_at=now - timedelta(days=1),
        )
        session.add_all([stale, fresh])
        await session.commit()

        deleted = await purge_notifications(session, now=now)
        await session.commit()

        assert deleted == 1
        remaining = (await session.execute(select(Notification))).scalars().all()
        assert [n.id for n in remaining] == [fresh.id]


async def test_purge_import_sessions_deletes_only_rows_expired_past_retention(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, email="import-cleanup@example.com")
        now = datetime.now(UTC)
        stale = ImportSession(
            user_id=user.id,
            file_name="a.csv",
            row_count=1,
            rows=[],
            status=ImportSessionStatus.CONFIRMED,
            expires_at=now - timedelta(days=settings.IMPORT_SESSION_RETENTION_DAYS + 1),
        )
        fresh = ImportSession(
            user_id=user.id,
            file_name="b.csv",
            row_count=1,
            rows=[],
            status=ImportSessionStatus.PENDING,
            expires_at=now - timedelta(minutes=1),
        )
        session.add_all([stale, fresh])
        await session.commit()

        deleted = await purge_import_sessions(session, now=now)
        await session.commit()

        assert deleted == 1
        remaining = (await session.execute(select(ImportSession))).scalars().all()
        assert [s.id for s in remaining] == [fresh.id]


async def test_purge_refresh_sessions_deletes_only_dead_rows_past_retention(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        user = await _make_user(session, email="refresh-cleanup@example.com")
        now = datetime.now(UTC)
        cutoff_breach = now - timedelta(days=settings.REFRESH_SESSION_RETENTION_DAYS + 1)

        long_expired = RefreshSession(
            user_id=user.id,
            refresh_token_hash="a",
            device=None,
            ip_address=None,
            user_agent=None,
            revoked=False,
            expires_at=cutoff_breach,
        )
        revoked_long_ago = RefreshSession(
            user_id=user.id,
            refresh_token_hash="b",
            device=None,
            ip_address=None,
            user_agent=None,
            revoked=True,
            expires_at=now + timedelta(days=10),
        )
        active = RefreshSession(
            user_id=user.id,
            refresh_token_hash="c",
            device=None,
            ip_address=None,
            user_agent=None,
            revoked=False,
            expires_at=now + timedelta(days=10),
        )
        session.add_all([long_expired, revoked_long_ago, active])
        await session.commit()

        # `updated_at` normally stamps at commit time via `onupdate`; back-
        # date it directly so the revoked row looks like it died well
        # before the retention window, without racing the ORM's own clock.
        await session.execute(
            update(RefreshSession)
            .where(RefreshSession.id == revoked_long_ago.id)
            .values(updated_at=cutoff_breach)
        )
        await session.commit()

        deleted = await purge_refresh_sessions(session, now=now)
        await session.commit()

        assert deleted == 2
        remaining = (await session.execute(select(RefreshSession))).scalars().all()
        assert [s.id for s in remaining] == [active.id]


async def test_purge_unverified_users_deletes_only_stale_unverified_accounts(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        now = datetime.now(UTC)
        cutoff_breach = now - timedelta(days=settings.USER_UNVERIFIED_RETENTION_DAYS + 1)

        stale_unverified = User(
            email="stale-unverified@example.com",
            username="stale_unverified",
            password_hash="x",
            is_verified=False,
            created_at=cutoff_breach,
        )
        fresh_unverified = User(
            email="fresh-unverified@example.com",
            username="fresh_unverified",
            password_hash="x",
            is_verified=False,
            created_at=now - timedelta(days=1),
        )
        stale_verified = User(
            email="stale-verified@example.com",
            username="stale_verified",
            password_hash="x",
            is_verified=True,
            created_at=cutoff_breach,
        )
        session.add_all([stale_unverified, fresh_unverified, stale_verified])
        await session.commit()

        deleted = await purge_unverified_users(session, now=now)
        await session.commit()

        assert deleted == 1
        remaining = {u.username for u in (await session.execute(select(User))).scalars().all()}
        assert remaining == {"fresh_unverified", "stale_verified"}
