"""Unit tests for `NotificationPreferenceService` — default resolution and
the create-on-first-update / update-on-subsequent upsert behavior.
"""

from datetime import time

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.enums import NotificationType
from src.modules.notifications.preferences.service import NotificationPreferenceService
from src.modules.users.models import User
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, login_user_a


async def _get_user_and_service(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AsyncSession, NotificationPreferenceService, User]:
    session = db_session_factory()
    users = UserRepository(session)
    user = await users.get_by_email(USER_A["email"])
    assert user is not None
    return session, NotificationPreferenceService(session), user


async def test_get_for_user_returns_default_when_no_row_exists(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        preference = await service.get_for_user(user.id, NotificationType.WELCOME)
        assert preference.is_default is True
        assert preference.enabled is True
        assert preference.in_app_enabled is True
        assert preference.email_enabled is False
        assert preference.delivery_time is None
        assert preference.timezone is None


async def test_list_for_user_returns_one_entry_per_notification_type(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        preferences = await service.list_for_user(user.id)
        assert {p.notification_type for p in preferences} == set(NotificationType)
        assert all(p.is_default for p in preferences)


async def test_update_for_user_creates_a_row_on_first_change(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        updated = await service.update_for_user(
            user.id, NotificationType.WELCOME, {"email_enabled": True}
        )
        assert updated.is_default is False
        assert updated.email_enabled is True
        # Untouched fields fall back to the default, not garbage.
        assert updated.enabled is True
        assert updated.in_app_enabled is True


async def test_update_for_user_only_changes_the_targeted_notification_type(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.update_for_user(user.id, NotificationType.WELCOME, {"enabled": False})
        other = await service.get_for_user(user.id, NotificationType.REPORT_READY)
        assert other.is_default is True
        assert other.enabled is True


async def test_update_for_user_upserts_on_a_second_call(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.update_for_user(user.id, NotificationType.WELCOME, {"email_enabled": True})
        updated = await service.update_for_user(
            user.id,
            NotificationType.WELCOME,
            {"delivery_time": time(9, 0), "timezone": "Asia/Kolkata"},
        )
        assert updated.email_enabled is True
        assert updated.delivery_time == time(9, 0)
        assert updated.timezone == "Asia/Kolkata"

        preferences = await service.list_for_user(user.id)
        matching = next(p for p in preferences if p.notification_type == NotificationType.WELCOME)
        assert matching.email_enabled is True
        assert matching.delivery_time == time(9, 0)
