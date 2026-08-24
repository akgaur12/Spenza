"""Integration tests for the /api/v1/admin/email endpoints."""

from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.database import get_db_session
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from tests.conftest import RecordingEmailBackend, promote_to_admin, register_verified_user
from tests.notifications.fakes import RecordingEmailProvider

ADMIN_CREDENTIALS = {"email": "admin.email@example.com", "password": "SecureP@ss1"}
ADMIN_SIGNUP_PAYLOAD = {**ADMIN_CREDENTIALS, "username": "admin_email_user"}
ADMIN_LOGIN_PAYLOAD = {
    "identifier": ADMIN_CREDENTIALS["email"],
    "password": ADMIN_CREDENTIALS["password"],
}

PLAIN_CREDENTIALS = {"email": "plain.email@example.com", "password": "SecureP@ss1"}
PLAIN_SIGNUP_PAYLOAD = {**PLAIN_CREDENTIALS, "username": "plain_email_user"}
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


# ── Config ───────────────────────────────────────────────────────────────


async def test_email_config_requires_admin(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)

    response = await client.get("/api/v1/admin/email/config")

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_email_config_reports_backend_without_leaking_secrets(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    response = await client.get("/api/v1/admin/email/config")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["backend"] == "console"
    assert data["sender_name"] == "Spenza"
    assert "resend_api_key" not in data
    assert "mailjet_api_secret" not in data
    assert "sender_password" not in data
    assert isinstance(data["resend_configured"], bool)
    assert isinstance(data["mailjet_configured"], bool)


# ── Send ─────────────────────────────────────────────────────────────────


async def _find_user_by_email(client: AsyncClient, email: str) -> dict[str, str]:
    list_response = await client.get("/api/v1/admin/users")
    return next(u for u in list_response.json()["data"]["items"] if u["email"] == email)


async def test_send_admin_email_requires_admin(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)

    response = await client.post(
        "/api/v1/admin/email/send",
        json={
            "user_ids": ["00000000-0000-0000-0000-000000000000"],
            "subject": "Hi",
            "message": "Hello",
        },
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_send_admin_email_to_specific_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])

    response = await client.post(
        "/api/v1/admin/email/send",
        json={
            "user_ids": [target["id"]],
            "subject": "Following up on your support request",
            "message": "The issue you reported has been fixed.",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["targeted"] == 1
    assert data["sent"] == 1
    assert data["failed"] == 0
    assert data["unknown_user_ids"] == []


async def test_send_admin_email_to_multiple_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])
    me_response = await client.get("/api/users/me")
    admin_id = me_response.json()["data"]["id"]

    response = await client.post(
        "/api/v1/admin/email/send",
        json={
            "user_ids": [target["id"], admin_id],
            "subject": "Scheduled maintenance",
            "message": "Downtime tonight.",
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["targeted"] == 2
    assert data["sent"] == 2


async def test_send_admin_email_reports_unknown_user_ids(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    unknown_id = "00000000-0000-0000-0000-000000000000"

    response = await client.post(
        "/api/v1/admin/email/send",
        json={"user_ids": [unknown_id], "subject": "Hi", "message": "Hello"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["targeted"] == 1
    assert data["sent"] == 0
    assert data["failed"] == 0
    assert data["unknown_user_ids"] == [unknown_id]


async def test_send_admin_email_renders_paragraphs_and_line_breaks(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from src.app import app as fastapi_app

    await _login_as_admin(client, email_backend, db_session_factory)
    me_response = await client.get("/api/users/me")
    admin_id = me_response.json()["data"]["id"]

    provider = RecordingEmailProvider()

    async def override_get_email_delivery_service(
        session: AsyncSession = Depends(get_db_session),
    ) -> EmailDeliveryService:
        return EmailDeliveryService(session, provider)

    fastapi_app.dependency_overrides[get_email_delivery_service] = (
        override_get_email_delivery_service
    )
    try:
        response = await client.post(
            "/api/v1/admin/email/send",
            json={
                "user_ids": [admin_id],
                "subject": "Happy Independence Day",
                "message": (
                    "Dear Spenza User,\n\n"
                    "Wishing you and your family a very Happy Independence Day!\n\n"
                    "Warm regards,\nTeam Spenza"
                ),
            },
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_email_delivery_service, None)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["sent"] == 1
    html_body = provider.sent[0]["html_body"]
    assert "<p>Dear Spenza User,</p>" in html_body
    assert "<p>Wishing you and your family a very Happy Independence Day!</p>" in html_body
    assert "<p>Warm regards,<br>Team Spenza</p>" in html_body


async def test_send_admin_email_reports_failure_without_raising(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from src.app import app as fastapi_app

    await _login_as_admin(client, email_backend, db_session_factory)
    me_response = await client.get("/api/users/me")
    admin_id = me_response.json()["data"]["id"]

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
        response = await client.post(
            "/api/v1/admin/email/send",
            json={"user_ids": [admin_id], "subject": "Hi", "message": "Hello"},
        )
    finally:
        fastapi_app.dependency_overrides.pop(get_email_delivery_service, None)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["sent"] == 0
    assert data["failed"] == 1
