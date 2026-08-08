"""Unit tests for `NotificationService`.

The delivery-channel group at the bottom mocks `InAppChannel`/`EmailChannel`
to verify `send()`'s dispatch contract — which channels get invoked, and
under what preference state — without re-testing what those channels
themselves do (already covered by `test_delivery.py`).
"""

import uuid
from unittest.mock import AsyncMock

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.enums import (
    DeliveryChannel,
    NotificationPriority,
    NotificationSortField,
    NotificationType,
    SortOrder,
)
from src.modules.notifications.exceptions import NotificationNotFoundError
from src.modules.notifications.service import NotificationService
from src.modules.users.models import User
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, login_user_a


async def _get_user_and_service(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AsyncSession, NotificationService, User]:
    session = db_session_factory()
    users = UserRepository(session)
    user = await users.get_by_email(USER_A["email"])
    assert user is not None
    return session, NotificationService(session), user


# ── send ─────────────────────────────────────────────────────────────────


async def test_send_creates_and_returns_a_notification(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        notification = await service.send(
            user_id=user.id,
            type=NotificationType.WELCOME,
            title="Welcome!",
            message="Thanks for joining Spenza.",
            payload={"foo": "bar"},
            priority=NotificationPriority.HIGH,
        )
        assert notification is not None
        assert notification.title == "Welcome!"
        assert notification.payload == {"foo": "bar"}
        assert notification.priority == NotificationPriority.HIGH
        assert notification.is_read is False


async def test_send_returns_none_when_type_is_disabled(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service._preferences.update_for_user(
            user.id, NotificationType.WELCOME, {"enabled": False}
        )
        notification = await service.send(
            user_id=user.id,
            type=NotificationType.WELCOME,
            title="Welcome!",
            message="Thanks for joining Spenza.",
        )
        assert notification is None

        items, total = await service.list_for_user(
            user.id,
            is_read=None,
            notification_type=None,
            priority=None,
            sort_by=NotificationSortField.CREATED_AT,
            sort_order=SortOrder.DESC,
            page=1,
            page_size=20,
        )
        assert total == 0
        assert items == []


async def test_send_defaults_payload_to_empty_dict(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        notification = await service.send(
            user_id=user.id,
            type=NotificationType.SYSTEM,
            title="System",
            message="Something happened.",
        )
        assert notification is not None
        assert notification.payload == {}
        assert notification.priority == NotificationPriority.NORMAL


# ── get / list / unread count ───────────────────────────────────────────


async def test_get_for_user_raises_not_found_for_unknown_id(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        try:
            await service.get_for_user(uuid.uuid4(), user.id)
            raise AssertionError("expected NotificationNotFoundError")
        except NotificationNotFoundError:
            pass


async def test_list_for_user_paginates(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        for i in range(3):
            await service.send(
                user_id=user.id,
                type=NotificationType.SYSTEM,
                title=f"Item {i}",
                message="msg",
            )
        items, total = await service.list_for_user(
            user.id,
            is_read=None,
            notification_type=None,
            priority=None,
            sort_by=NotificationSortField.CREATED_AT,
            sort_order=SortOrder.DESC,
            page=1,
            page_size=2,
        )
        assert total == 3
        assert len(items) == 2


async def test_unread_count_for_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.send(user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a")
        await service.send(user_id=user.id, type=NotificationType.SYSTEM, title="B", message="b")
        assert await service.unread_count_for_user(user.id) == 2


# ── mark read / mark all read / delete ──────────────────────────────────


async def test_mark_read_for_user_sets_is_read_and_read_at(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        notification = await service.send(
            user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a"
        )
        assert notification is not None
        updated = await service.mark_read_for_user(notification.id, user.id)
        assert updated.is_read is True
        assert updated.read_at is not None


async def test_mark_read_is_idempotent(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        notification = await service.send(
            user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a"
        )
        assert notification is not None
        first = await service.mark_read_for_user(notification.id, user.id)
        second = await service.mark_read_for_user(notification.id, user.id)
        assert first.read_at == second.read_at


async def test_mark_all_read_for_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.send(user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a")
        await service.send(user_id=user.id, type=NotificationType.SYSTEM, title="B", message="b")
        updated = await service.mark_all_read_for_user(user.id)
        assert updated == 2
        assert await service.unread_count_for_user(user.id) == 0


async def test_delete_for_user_removes_the_notification(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        notification = await service.send(
            user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a"
        )
        assert notification is not None
        await service.delete_for_user(notification.id, user.id)
        try:
            await service.get_for_user(notification.id, user.id)
            raise AssertionError("expected NotificationNotFoundError")
        except NotificationNotFoundError:
            pass


async def test_delete_for_user_raises_not_found_for_another_owner(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        notification = await service.send(
            user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a"
        )
        assert notification is not None
        try:
            await service.delete_for_user(notification.id, uuid.uuid4())
            raise AssertionError("expected NotificationNotFoundError")
        except NotificationNotFoundError:
            pass


# ── delivery-channel dispatch contract ──────────────────────────────────


async def test_send_always_invokes_in_app_channel_by_default(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        mock_in_app = AsyncMock()
        mock_email = AsyncMock()
        service._channels[DeliveryChannel.IN_APP] = mock_in_app
        service._channels[DeliveryChannel.EMAIL] = mock_email

        await service.send(user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a")

        mock_in_app.send.assert_awaited_once()
        mock_email.send.assert_not_awaited()


async def test_send_invokes_email_channel_only_when_preference_enables_it(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service._preferences.update_for_user(
            user.id, NotificationType.SYSTEM, {"email_enabled": True}
        )
        mock_in_app = AsyncMock()
        mock_email = AsyncMock()
        service._channels[DeliveryChannel.IN_APP] = mock_in_app
        service._channels[DeliveryChannel.EMAIL] = mock_email

        await service.send(user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a")

        mock_in_app.send.assert_awaited_once()
        mock_email.send.assert_awaited_once()


async def test_send_skips_all_channels_when_type_disabled(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service._preferences.update_for_user(
            user.id, NotificationType.SYSTEM, {"enabled": False}
        )
        mock_in_app = AsyncMock()
        mock_email = AsyncMock()
        service._channels[DeliveryChannel.IN_APP] = mock_in_app
        service._channels[DeliveryChannel.EMAIL] = mock_email

        result = await service.send(
            user_id=user.id, type=NotificationType.SYSTEM, title="A", message="a"
        )

        assert result is None
        mock_in_app.send.assert_not_awaited()
        mock_email.send.assert_not_awaited()
