"""Integration tests for the /api/admin/users endpoints."""

from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.app_config import settings
from src.core.database import get_db_session
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus
from src.modules.notifications.models import NotificationDeliveryLog
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from tests.conftest import RecordingEmailBackend, promote_to_admin, register_verified_user
from tests.notifications.fakes import RecordingEmailProvider

ADMIN_CREDENTIALS = {"email": "admin@example.com", "password": "SecureP@ss1"}
ADMIN_SIGNUP_PAYLOAD = {**ADMIN_CREDENTIALS, "username": "admin_user"}
ADMIN_LOGIN_PAYLOAD = {
    "identifier": ADMIN_CREDENTIALS["email"],
    "password": ADMIN_CREDENTIALS["password"],
}

PLAIN_CREDENTIALS = {"email": "plain.user@example.com", "password": "SecureP@ss1"}
PLAIN_SIGNUP_PAYLOAD = {**PLAIN_CREDENTIALS, "username": "plain_user"}
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


async def _find_user_by_email(client: AsyncClient, email: str) -> dict[str, str]:
    """List every user as the currently-authenticated admin and return the
    one matching `email`.
    """
    list_response = await client.get("/api/admin/users")
    return next(u for u in list_response.json()["data"]["items"] if u["email"] == email)


# ── Access control ───────────────────────────────────────────────────────


async def test_list_users_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/admin/users")
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_ACCESS_TOKEN"


async def test_list_users_rejects_non_admin(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)

    response = await client.get("/api/admin/users")

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


# ── List / get ───────────────────────────────────────────────────────────


async def test_list_users_returns_all_users_paginated(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)

    response = await client.get("/api/admin/users", params={"page": 1, "page_size": 20})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 20
    emails = {u["email"] for u in data["items"]}
    assert emails == {ADMIN_CREDENTIALS["email"], PLAIN_CREDENTIALS["email"]}


async def test_get_user_by_id_returns_full_detail(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])

    response = await client.get(f"/api/admin/users/{target['id']}")

    assert response.status_code == 200
    assert response.json()["data"]["email"] == PLAIN_CREDENTIALS["email"]


async def test_get_user_by_id_unknown_returns_404(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    response = await client.get("/api/admin/users/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["error_code"] == "USER_NOT_FOUND"


# ── Activate / deactivate ────────────────────────────────────────────────


async def test_deactivate_and_reactivate_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])

    deactivate_response = await client.patch(
        f"/api/admin/users/{target['id']}/active", json={"is_active": False}
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["data"]["is_active"] is False

    login_response = await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)
    assert login_response.status_code == 403
    assert login_response.json()["error_code"] == "ACCOUNT_INACTIVE"

    reactivate_response = await client.patch(
        f"/api/admin/users/{target['id']}/active", json={"is_active": True}
    )
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["data"]["is_active"] is True


# ── Unlock ───────────────────────────────────────────────────────────────


async def test_unlock_user_resets_lockout(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)

    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        await client.post(
            "/api/users/login",
            json={"identifier": PLAIN_CREDENTIALS["email"], "password": "WrongPassword1!"},
        )
    locked_response = await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)
    assert locked_response.status_code == 429

    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])
    unlock_response = await client.post(f"/api/admin/users/{target['id']}/unlock")
    assert unlock_response.status_code == 200
    assert unlock_response.json()["data"]["locked_until"] is None

    login_response = await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)
    assert login_response.status_code == 200


# ── Delete ───────────────────────────────────────────────────────────────


async def test_admin_delete_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])

    delete_response = await client.delete(f"/api/admin/users/{target['id']}")
    assert delete_response.status_code == 200

    get_response = await client.get(f"/api/admin/users/{target['id']}")
    assert get_response.status_code == 404


async def test_admin_delete_user_emails_expense_data_export_to_target_first(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])

    delete_response = await client.delete(f"/api/admin/users/{target['id']}")
    assert delete_response.status_code == 200, delete_response.text

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


async def test_admin_delete_user_is_blocked_when_export_email_fails(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from src.app import app as fastapi_app

    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    target = await _find_user_by_email(client, PLAIN_CREDENTIALS["email"])

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
        delete_response = await client.delete(f"/api/admin/users/{target['id']}")
        assert delete_response.status_code == 503
        assert delete_response.json()["error_code"] == "ACCOUNT_DATA_EXPORT_FAILED"
    finally:
        fastapi_app.dependency_overrides.pop(get_email_delivery_service, None)

    # The target account must still exist — deletion must not have proceeded.
    get_response = await client.get(f"/api/admin/users/{target['id']}")
    assert get_response.status_code == 200


# ── Self-lockout guard ───────────────────────────────────────────────────


async def test_admin_cannot_deactivate_own_account(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    me_response = await client.get("/api/users/me")
    admin_id = me_response.json()["data"]["id"]

    response = await client.patch(f"/api/admin/users/{admin_id}/active", json={"is_active": False})

    assert response.status_code == 400
    assert response.json()["error_code"] == "CANNOT_MODIFY_OWN_ACCOUNT"


async def test_admin_cannot_delete_own_account(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)

    me_response = await client.get("/api/users/me")
    admin_id = me_response.json()["data"]["id"]

    response = await client.delete(f"/api/admin/users/{admin_id}")

    assert response.status_code == 400
    assert response.json()["error_code"] == "CANNOT_MODIFY_OWN_ACCOUNT"
