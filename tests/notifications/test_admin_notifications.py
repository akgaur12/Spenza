"""Integration tests for the /api/v1/admin/notifications endpoints."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.notifications.delivery_log_repository import NotificationDeliveryLogRepository
from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus
from tests.conftest import RecordingEmailBackend, promote_to_admin, register_verified_user

ADMIN_CREDENTIALS = {"email": "admin.notif@example.com", "password": "SecureP@ss1"}
ADMIN_SIGNUP_PAYLOAD = {**ADMIN_CREDENTIALS, "username": "admin_notif_user"}
ADMIN_LOGIN_PAYLOAD = {
    "identifier": ADMIN_CREDENTIALS["email"],
    "password": ADMIN_CREDENTIALS["password"],
}

PLAIN_CREDENTIALS = {"email": "plain.notif@example.com", "password": "SecureP@ss1"}
PLAIN_SIGNUP_PAYLOAD = {**PLAIN_CREDENTIALS, "username": "plain_notif_user"}
PLAIN_LOGIN_PAYLOAD = {
    "identifier": PLAIN_CREDENTIALS["email"],
    "password": PLAIN_CREDENTIALS["password"],
}


async def _login_as_admin(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_verified_user(client, email_backend, ADMIN_SIGNUP_PAYLOAD)
    await promote_to_admin(db_session_factory, ADMIN_CREDENTIALS["email"])
    response = await client.post("/api/users/login", json=ADMIN_LOGIN_PAYLOAD)
    assert response.status_code == 200, response.text


# ── Broadcast ────────────────────────────────────────────────────────────


async def test_broadcast_requires_admin(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)

    response = await client.post(
        "/api/v1/admin/notifications/broadcast",
        json={"title": "Hi", "message": "Hello"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_broadcast_to_all_active_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)

    response = await client.post(
        "/api/v1/admin/notifications/broadcast",
        json={"title": "Scheduled maintenance", "message": "Downtime tonight"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    # The admin account itself plus the newly registered plain user.
    assert data["targeted"] == 2
    assert data["sent"] == 2
    assert data["skipped"] == 0

    my_notifications = await client.get("/api/v1/notifications")
    titles = [n["title"] for n in my_notifications.json()["data"]["items"]]
    assert "Scheduled maintenance" in titles


async def test_broadcast_to_specific_user_ids(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    signup_response = await client.post("/api/users/signup", json=PLAIN_SIGNUP_PAYLOAD)
    assert signup_response.status_code == 201

    users_response = await client.get("/api/v1/admin/users")
    target = next(
        u
        for u in users_response.json()["data"]["items"]
        if u["email"] == PLAIN_CREDENTIALS["email"]
    )

    response = await client.post(
        "/api/v1/admin/notifications/broadcast",
        json={"title": "Just you", "message": "Targeted message", "user_ids": [target["id"]]},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["targeted"] == 1
    assert data["sent"] == 1


async def test_broadcast_skips_users_with_type_disabled(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    me_response = await client.get("/api/users/me")
    admin_id = me_response.json()["data"]["id"]

    disable_response = await client.patch(
        "/api/v1/notification-preferences/system", json={"enabled": False}
    )
    assert disable_response.status_code == 200, disable_response.text

    response = await client.post(
        "/api/v1/admin/notifications/broadcast",
        json={"title": "Hi", "message": "Hello", "user_ids": [admin_id]},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["targeted"] == 1
    assert data["sent"] == 0
    assert data["skipped"] == 1


# ── Delivery logs ────────────────────────────────────────────────────────


async def test_delivery_logs_requires_admin(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)

    response = await client.get("/api/v1/admin/notifications/delivery-logs")

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_delivery_logs_filters_by_status(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    async with db_session_factory() as session:
        logs = NotificationDeliveryLogRepository(session)
        logs.create(
            notification_id=None,
            channel=DeliveryChannel.EMAIL,
            status=DeliveryLogStatus.SUCCESS,
            attempt=1,
        )
        logs.create(
            notification_id=None,
            channel=DeliveryChannel.EMAIL,
            status=DeliveryLogStatus.FAILED,
            attempt=1,
            error_message="SMTP timeout",
        )
        await session.commit()

    all_response = await client.get("/api/v1/admin/notifications/delivery-logs")
    assert all_response.status_code == 200, all_response.text
    assert all_response.json()["data"]["total"] == 2

    failed_response = await client.get(
        "/api/v1/admin/notifications/delivery-logs", params={"status": "failed"}
    )
    assert failed_response.status_code == 200, failed_response.text
    failed_data = failed_response.json()["data"]
    assert failed_data["total"] == 1
    assert failed_data["items"][0]["error_message"] == "SMTP timeout"
