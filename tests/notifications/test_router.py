"""Integration tests for `/api/v1/notifications` and
`/api/v1/notification-preferences`.

No creation endpoint exists (by design — see `router.py`'s docstring), so
every test seeds notifications directly via `NotificationService.send()`
against the test session, then exercises the HTTP surface on top of that
seeded state.
"""

from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.database import get_db_session
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.enums import NotificationPriority, NotificationType
from src.modules.notifications.service import NotificationService
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, login_user_a, login_user_b, switch_to_user_a
from tests.notifications.fakes import RecordingEmailProvider
from tests.notifications.helpers import (
    delete_notification,
    list_notification_preferences,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    update_notification_preference,
)


async def _send_notification(
    db_session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str = USER_A["email"],
    notification_type: NotificationType = NotificationType.SYSTEM,
    title: str = "Hello",
    message: str = "World",
    priority: NotificationPriority = NotificationPriority.NORMAL,
) -> str:
    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email(email)
        assert user is not None
        service = NotificationService(session)
        notification = await service.send(
            user_id=user.id,
            type=notification_type,
            title=title,
            message=message,
            priority=priority,
        )
        await session.commit()
        assert notification is not None
        return str(notification.id)


async def test_list_notifications_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/notifications")
    assert response.status_code == 401


async def test_list_notifications_returns_own_notifications_newest_first(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await _send_notification(db_session_factory, title="First")
    await _send_notification(db_session_factory, title="Second")

    data = await list_notifications(client)
    assert data["total"] == 2
    assert [item["title"] for item in data["items"]] == ["Second", "First"]


async def test_list_notifications_filters_by_is_read(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    unread_id = await _send_notification(db_session_factory, title="Unread")
    read_id = await _send_notification(db_session_factory, title="Read")
    await mark_notification_read(client, read_id)

    data = await list_notifications(client, is_read="false")
    assert data["total"] == 1
    assert data["items"][0]["id"] == unread_id

    data = await list_notifications(client, is_read="true")
    assert data["total"] == 1
    assert data["items"][0]["id"] == read_id


async def test_list_notifications_filters_by_type_and_priority(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await _send_notification(
        db_session_factory, notification_type=NotificationType.WELCOME, title="Welcome"
    )
    await _send_notification(
        db_session_factory,
        notification_type=NotificationType.REPORT_READY,
        title="Report",
        priority=NotificationPriority.HIGH,
    )

    data = await list_notifications(client, notification_type="welcome")
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Welcome"

    data = await list_notifications(client, priority="high")
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Report"


async def test_list_notifications_paginates(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    for i in range(3):
        await _send_notification(db_session_factory, title=f"Item {i}")

    data = await list_notifications(client, page=1, page_size=2)
    assert data["total"] == 3
    assert data["total_pages"] == 2
    assert len(data["items"]) == 2


async def test_list_notifications_only_shows_current_users_own(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await _send_notification(db_session_factory)

    await login_user_b(client, email_backend)
    data = await list_notifications(client)
    assert data["total"] == 0


async def test_unread_count(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await _send_notification(db_session_factory, title="A")
    await _send_notification(db_session_factory, title="B")

    response = await client.get("/api/v1/notifications/unread-count")
    assert response.status_code == 200
    assert response.json()["data"]["count"] == 2


async def test_mark_notification_read(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    notification_id = await _send_notification(db_session_factory)

    response = await mark_notification_read(client, notification_id)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["is_read"] is True
    assert data["read_at"] is not None


async def test_mark_unknown_notification_read_is_not_found(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await mark_notification_read(client, "00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOTIFICATION_NOT_FOUND"


async def test_mark_another_users_notification_read_is_not_found(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    notification_id = await _send_notification(db_session_factory)

    await login_user_b(client, email_backend)
    response = await mark_notification_read(client, notification_id)
    assert response.status_code == 404


async def test_mark_all_notifications_read(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await _send_notification(db_session_factory, title="A")
    await _send_notification(db_session_factory, title="B")

    response = await mark_all_notifications_read(client)
    assert response.status_code == 200
    assert response.json()["data"]["updated"] == 2

    count_response = await client.get("/api/v1/notifications/unread-count")
    assert count_response.json()["data"]["count"] == 0


async def test_delete_notification(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    notification_id = await _send_notification(db_session_factory)

    response = await delete_notification(client, notification_id)
    assert response.status_code == 204

    response = await mark_notification_read(client, notification_id)
    assert response.status_code == 404


async def test_delete_another_users_notification_is_not_found(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    notification_id = await _send_notification(db_session_factory)

    await login_user_b(client, email_backend)
    response = await delete_notification(client, notification_id)
    assert response.status_code == 404

    await switch_to_user_a(client)
    response = await mark_notification_read(client, notification_id)
    assert response.status_code == 200


# ── preferences ──────────────────────────────────────────────────────────


async def test_list_notification_preferences_requires_authentication(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/notification-preferences")
    assert response.status_code == 401


async def test_list_notification_preferences_returns_defaults_for_every_type(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await list_notification_preferences(client)
    types = {item["notification_type"] for item in data["items"]}
    assert types == set(NotificationType)
    assert all(item["is_default"] for item in data["items"])


async def test_update_notification_preference(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await update_notification_preference(
        client, "welcome", {"email_enabled": True, "delivery_time": "09:00:00"}
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["email_enabled"] is True
    assert data["delivery_time"] == "09:00:00"
    assert data["is_default"] is False


async def test_update_notification_preference_rejects_invalid_timezone(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await update_notification_preference(
        client, "welcome", {"timezone": "Not/A_Real_Zone"}
    )
    assert response.status_code == 422


async def test_update_notification_preference_persists_across_requests(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await update_notification_preference(client, "welcome", {"enabled": False})

    data = await list_notification_preferences(client)
    welcome = next(item for item in data["items"] if item["notification_type"] == "welcome")
    assert welcome["enabled"] is False
    assert welcome["is_default"] is False


async def test_update_notification_preference_rejects_invalid_type(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await update_notification_preference(client, "not_a_real_type", {"enabled": False})
    assert response.status_code == 422


async def test_send_respects_a_disabled_preference_end_to_end(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    await update_notification_preference(client, "welcome", {"enabled": False})

    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email(USER_A["email"])
        assert user is not None
        service = NotificationService(session)
        result = await service.send(
            user_id=user.id, type=NotificationType.WELCOME, title="Welcome!", message="Hi"
        )
        await session.commit()
        assert result is None

    data = await list_notifications(client)
    assert data["total"] == 0


# ── test-email ───────────────────────────────────────────────────────────


async def test_send_test_email_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/api/v1/notifications/test-email")
    assert response.status_code == 401


async def test_send_test_email_sends_to_the_current_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post("/api/v1/notifications/test-email")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["sent_to"] == USER_A["email"]


async def test_send_test_email_returns_503_when_delivery_fails(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    from src.app import app as fastapi_app

    await login_user_a(client, email_backend)

    async def override_get_email_delivery_service(
        session: AsyncSession = Depends(get_db_session),
    ) -> EmailDeliveryService:
        return EmailDeliveryService(
            session,
            RecordingEmailProvider(always_fail=True),
            max_retries=1,
            retry_base_delay_seconds=0,
        )

    fastapi_app.dependency_overrides[get_email_delivery_service] = (
        override_get_email_delivery_service
    )
    try:
        response = await client.post("/api/v1/notifications/test-email")
        assert response.status_code == 503
        assert response.json()["error_code"] == "EMAIL_DELIVERY_FAILED"
    finally:
        fastapi_app.dependency_overrides.pop(get_email_delivery_service, None)
