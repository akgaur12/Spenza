"""Unit tests for `EmailDeliveryService` — retry/backoff and
`notification_delivery_logs` bookkeeping, in isolation from any HTTP layer.

`retry_base_delay_seconds=0` throughout so retry tests don't actually sleep.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus
from src.modules.notifications.models import NotificationDeliveryLog
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from tests.notifications.fakes import RecordingEmailProvider


async def _logs_for(
    session: AsyncSession, notification_id: uuid.UUID | None
) -> list[NotificationDeliveryLog]:
    result = await session.execute(
        select(NotificationDeliveryLog)
        .where(NotificationDeliveryLog.notification_id == notification_id)
        .order_by(NotificationDeliveryLog.attempt.asc())
    )
    return list(result.scalars().all())


async def test_send_succeeds_on_first_attempt(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        provider = RecordingEmailProvider()
        service = EmailDeliveryService(session, provider, max_retries=3, retry_base_delay_seconds=0)
        notification_id = uuid.uuid4()

        delivered = await service.send(
            to="user@example.com",
            subject="Hi",
            html_body="<p>hi</p>",
            notification_id=notification_id,
        )
        await session.commit()

        assert delivered is True
        assert provider.call_count == 1
        logs = await _logs_for(session, notification_id)
        assert len(logs) == 1
        assert logs[0].status is DeliveryLogStatus.SUCCESS
        assert logs[0].attempt == 1
        assert logs[0].channel is DeliveryChannel.EMAIL
        assert logs[0].provider == "fake"
        assert logs[0].sent_at is not None


async def test_send_retries_and_eventually_succeeds(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        provider = RecordingEmailProvider(fail_times=2)
        service = EmailDeliveryService(session, provider, max_retries=3, retry_base_delay_seconds=0)
        notification_id = uuid.uuid4()

        delivered = await service.send(
            to="user@example.com",
            subject="Hi",
            html_body="<p>hi</p>",
            notification_id=notification_id,
        )
        await session.commit()

        assert delivered is True
        assert provider.call_count == 3
        logs = await _logs_for(session, notification_id)
        assert [log.status for log in logs] == [
            DeliveryLogStatus.FAILED,
            DeliveryLogStatus.FAILED,
            DeliveryLogStatus.SUCCESS,
        ]
        assert [log.attempt for log in logs] == [1, 2, 3]
        assert logs[0].error_message is not None


async def test_send_gives_up_after_max_retries(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        provider = RecordingEmailProvider(always_fail=True)
        service = EmailDeliveryService(session, provider, max_retries=3, retry_base_delay_seconds=0)
        notification_id = uuid.uuid4()

        delivered = await service.send(
            to="user@example.com",
            subject="Hi",
            html_body="<p>hi</p>",
            notification_id=notification_id,
        )
        await session.commit()

        assert delivered is False
        assert provider.call_count == 3
        logs = await _logs_for(session, notification_id)
        assert len(logs) == 3
        assert all(log.status is DeliveryLogStatus.FAILED for log in logs)


async def test_send_never_raises_even_when_provider_always_fails(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        provider = RecordingEmailProvider(always_fail=True)
        service = EmailDeliveryService(session, provider, max_retries=2, retry_base_delay_seconds=0)
        # Must not raise — a failed delivery is a `False` return, never an exception.
        delivered = await service.send(to="user@example.com", subject="Hi", html_body="<p>hi</p>")
        assert delivered is False


async def test_send_logs_with_null_notification_id_for_standalone_sends(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        provider = RecordingEmailProvider()
        service = EmailDeliveryService(session, provider, max_retries=3, retry_base_delay_seconds=0)

        delivered = await service.send(to="user@example.com", subject="Test", html_body="<p>x</p>")
        await session.commit()

        assert delivered is True
        logs = await _logs_for(session, None)
        assert len(logs) == 1
        assert logs[0].notification_id is None


async def test_send_passes_attachments_through_to_the_provider(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from src.modules.notifications.delivery.provider import EmailAttachment

    async with db_session_factory() as session:
        provider = RecordingEmailProvider()
        service = EmailDeliveryService(session, provider, max_retries=3, retry_base_delay_seconds=0)
        attachment = EmailAttachment(filename="r.pdf", content=b"abc", mime_type="application/pdf")

        await service.send(
            to="user@example.com", subject="Hi", html_body="<p>hi</p>", attachments=[attachment]
        )

        assert provider.sent[0]["attachments"] == [attachment]


async def test_default_settings_max_retries_used_when_not_overridden(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from src.core.app_config import settings

    async with db_session_factory() as session:
        provider = RecordingEmailProvider(always_fail=True)
        service = EmailDeliveryService(session, provider, retry_base_delay_seconds=0)

        await service.send(to="user@example.com", subject="Hi", html_body="<p>hi</p>")

        assert provider.call_count == settings.EMAIL_MAX_RETRIES
