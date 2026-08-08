"""Tests for the delivery channel abstraction.

`InAppChannel` just logs — those tests stay a one-liner smoke check. `Email
Channel` is fully wired in Phase 11B: it looks up the recipient, renders a
template, and delegates to `EmailDeliveryService`, using an injected
`RecordingEmailProvider` so nothing ever touches the network.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.delivery.base import BaseNotificationChannel
from src.modules.notifications.delivery.email import EmailChannel
from src.modules.notifications.delivery.in_app import InAppChannel
from src.modules.notifications.enums import NotificationPriority, NotificationType
from src.modules.notifications.models import Notification
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, login_user_a
from tests.notifications.fakes import RecordingEmailProvider


def _sample_notification(
    *,
    user_id: uuid.UUID | None = None,
    notification_type: NotificationType = NotificationType.SYSTEM,
) -> Notification:
    return Notification(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        type=notification_type,
        title="Test",
        message="Test message",
        payload={},
        priority=NotificationPriority.NORMAL,
        is_read=False,
        read_at=None,
        created_at=datetime.now(UTC),
    )


async def test_in_app_channel_send_completes_without_error() -> None:
    await InAppChannel().send(_sample_notification())


def test_base_channel_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BaseNotificationChannel()  # type: ignore[abstract]


async def test_email_channel_sends_to_the_notifications_owner(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        provider = RecordingEmailProvider()
        channel = EmailChannel(session, provider)

        notification = _sample_notification(user_id=user.id)
        await channel.send(notification)
        await session.commit()

        assert len(provider.sent) == 1
        assert provider.sent[0]["to"] == USER_A["email"]
        assert "Test" in str(provider.sent[0]["subject"])


async def test_email_channel_uses_recurring_expense_template(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        provider = RecordingEmailProvider()
        channel = EmailChannel(session, provider)

        notification = _sample_notification(
            user_id=user.id, notification_type=NotificationType.RECURRING_EXPENSE_CREATED
        )
        notification.payload = {"amount": "45.00", "category_name": "Groceries"}
        await channel.send(notification)

        assert len(provider.sent) == 1
        html_body = str(provider.sent[0]["html_body"])
        assert "45.00" in html_body
        assert "Groceries" in html_body


async def test_email_channel_skips_report_ready_notifications(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The report itself is emailed directly by the report job with its PDF
    attached — a plain `EmailChannel` send here would be a redundant
    duplicate (see `EmailChannel`'s module docstring).
    """
    await login_user_a(client, email_backend)
    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        provider = RecordingEmailProvider()
        channel = EmailChannel(session, provider)

        notification = _sample_notification(
            user_id=user.id, notification_type=NotificationType.REPORT_READY
        )
        await channel.send(notification)

        assert provider.sent == []


async def test_email_channel_skips_when_user_not_found(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        provider = RecordingEmailProvider()
        channel = EmailChannel(session, provider)

        await channel.send(_sample_notification(user_id=uuid.uuid4()))

        assert provider.sent == []
