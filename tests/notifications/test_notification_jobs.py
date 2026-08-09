"""Tests for the hourly pending-notification-email sweep job.

The normal path (a notification created through `NotificationService.send()`
with `email_enabled=True`) already resolves to `SUCCESS`/exhausted-`FAILED`
before this job would ever see it — see `EmailChannel`. So these tests
simulate the one case this job exists for: a notification with an
email-enabled preference but no delivery log at all yet (as if the process
died before `EmailChannel` ever ran).
"""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.enums import (
    DeliveryLogStatus,
    NotificationPriority,
    NotificationType,
)
from src.modules.notifications.jobs.notification_jobs import process_pending_notification_emails
from src.modules.notifications.models import NotificationDeliveryLog
from src.modules.notifications.repository import NotificationRepository
from src.modules.notifications.service import NotificationService
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, login_user_a
from tests.notifications.helpers import update_notification_preference


async def test_sweep_finds_nothing_when_no_notifications_exist(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        summary = await process_pending_notification_emails(session)
        assert summary.checked == 0


async def test_sweep_ignores_notifications_without_email_preference(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        repo = NotificationRepository(session)
        repo.create(
            user_id=user.id,
            notification_type=NotificationType.SYSTEM,
            title="Hi",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        await repo.flush()
        await session.commit()

        summary = await process_pending_notification_emails(session)
        assert summary.checked == 0


async def test_sweep_delivers_a_notification_with_no_prior_delivery_log(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await update_notification_preference(client, "system", {"email_enabled": True})

    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        repo = NotificationRepository(session)
        notification = repo.create(
            user_id=user.id,
            notification_type=NotificationType.SYSTEM,
            title="Crashed before delivery",
            message="msg",
            payload={},
            priority=NotificationPriority.NORMAL,
        )
        await repo.flush()
        await session.commit()
        notification_id = notification.id

        summary = await process_pending_notification_emails(session)
        assert summary.checked == 1

        logs = (
            (
                await session.execute(
                    select(NotificationDeliveryLog).where(
                        NotificationDeliveryLog.notification_id == notification_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(log.status is DeliveryLogStatus.SUCCESS for log in logs)


async def test_sweep_does_not_redeliver_an_already_successful_notification(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await update_notification_preference(client, "system", {"email_enabled": True})

    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        notification = await NotificationService(session).send(
            user_id=user.id, type=NotificationType.SYSTEM, title="Hi", message="msg"
        )
        await session.commit()
        assert notification is not None

        summary = await process_pending_notification_emails(session)
        assert summary.checked == 0
