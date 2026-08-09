"""Integration tests for `PASSWORD_CHANGED` notifications wired into both
password-change flows (`change_password` while authenticated, and
`reset_password` via the forgot-password/OTP flow).

Covers:
- both flows create an in-app notification
- `PASSWORD_CHANGED` defaults to `email_enabled=True` (unlike every other
  notification type, which defaults to email off) — see
  `preferences.service._EMAIL_ENABLED_BY_DEFAULT_TYPES`
- a failure inside the notification layer never blocks or rolls back an
  otherwise-successful password change — see `user_router._notify_password_changed`
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus, NotificationType
from src.modules.notifications.models import NotificationDeliveryLog
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend, register_verified_user
from tests.import_export.helpers import USER_A, USER_A_SIGNUP, login_user_a
from tests.notifications.helpers import list_notification_preferences, list_notifications

NEW_PASSWORD = "NewSecureP@ss1"


async def _get_reset_token(client: AsyncClient, email_backend: RecordingEmailBackend) -> str:
    email_backend.sent.clear()
    await client.post("/api/users/forgot-password", json={"email": USER_A["email"]})
    otp = email_backend.latest_otp(USER_A["email"])
    response = await client.post(
        "/api/users/verify-reset-otp", json={"email": USER_A["email"], "otp": otp}
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["data"]["reset_token"]
    return token


async def test_password_changed_defaults_to_email_enabled_unlike_other_types(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await list_notification_preferences(client)
    by_type = {item["notification_type"]: item for item in data["items"]}

    password_changed = by_type["password_changed"]
    assert password_changed["is_default"] is True
    assert password_changed["enabled"] is True
    assert password_changed["in_app_enabled"] is True
    assert password_changed["email_enabled"] is True

    # Every other type's default is unaffected by this override.
    for notification_type, item in by_type.items():
        if notification_type == "password_changed":
            continue
        assert item["email_enabled"] is False, f"{notification_type} should default to email off"


async def test_change_password_creates_in_app_notification_and_emails_it(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)

    response = await client.post(
        "/api/users/change-password",
        json={"current_password": USER_A["password"], "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text

    # `change_password` revokes sessions/clears cookies, so log back in to read notifications.
    await client.post(
        "/api/users/login", json={"identifier": USER_A["email"], "password": NEW_PASSWORD}
    )

    notifications = await list_notifications(client)
    assert notifications["total"] == 1
    assert notifications["items"][0]["type"] == "password_changed"

    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(USER_A["email"])
        assert user is not None
        logs = (
            (
                await session.execute(
                    select(NotificationDeliveryLog).where(
                        NotificationDeliveryLog.channel == DeliveryChannel.EMAIL
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        assert logs[0].status is DeliveryLogStatus.SUCCESS


async def test_reset_password_creates_in_app_notification_and_emails_it(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    reset_token = await _get_reset_token(client, email_backend)

    response = await client.post(
        "/api/users/reset-password",
        json={"reset_token": reset_token, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text

    await client.post(
        "/api/users/login", json={"identifier": USER_A["email"], "password": NEW_PASSWORD}
    )
    notifications = await list_notifications(client)
    assert notifications["total"] == 1
    assert notifications["items"][0]["type"] == "password_changed"

    async with db_session_factory() as session:
        logs = (
            (
                await session.execute(
                    select(NotificationDeliveryLog).where(
                        NotificationDeliveryLog.channel == DeliveryChannel.EMAIL
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) == 1
        assert logs[0].status is DeliveryLogStatus.SUCCESS


async def test_change_password_succeeds_even_if_notification_layer_raises(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    with patch(
        "src.modules.notifications.service.NotificationService.send",
        new=AsyncMock(side_effect=RuntimeError("simulated notification-layer failure")),
    ):
        await login_user_a(client, email_backend)
        response = await client.post(
            "/api/users/change-password",
            json={"current_password": USER_A["password"], "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 200, response.text

    # The password really changed, despite the notification call raising —
    # a login with the OLD password must fail and the NEW one must succeed.
    old_login = await client.post(
        "/api/users/login", json={"identifier": USER_A["email"], "password": USER_A["password"]}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/users/login", json={"identifier": USER_A["email"], "password": NEW_PASSWORD}
    )
    assert new_login.status_code == 200


async def test_reset_password_succeeds_even_if_notification_layer_raises(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    reset_token = await _get_reset_token(client, email_backend)

    with patch(
        "src.modules.notifications.service.NotificationService.send",
        new=AsyncMock(side_effect=RuntimeError("simulated notification-layer failure")),
    ):
        response = await client.post(
            "/api/users/reset-password",
            json={"reset_token": reset_token, "new_password": NEW_PASSWORD},
        )
        assert response.status_code == 200, response.text

    new_login = await client.post(
        "/api/users/login", json={"identifier": USER_A["email"], "password": NEW_PASSWORD}
    )
    assert new_login.status_code == 200


async def test_password_changed_notification_payload_has_no_sensitive_data(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await client.post(
        "/api/users/change-password",
        json={"current_password": USER_A["password"], "new_password": NEW_PASSWORD},
    )
    await client.post(
        "/api/users/login", json={"identifier": USER_A["email"], "password": NEW_PASSWORD}
    )
    notifications = await list_notifications(client)
    notification = notifications["items"][0]
    assert notification["payload"] == {}
    serialized = str(notification)
    assert USER_A["password"] not in serialized
    assert NEW_PASSWORD not in serialized


async def test_password_changed_notification_type_exists() -> None:
    assert NotificationType.PASSWORD_CHANGED.value == "password_changed"
