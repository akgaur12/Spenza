"""Integration tests for DELETE /api/users/delete-user."""

from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.database import get_db_session
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus
from src.modules.notifications.models import NotificationDeliveryLog
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from tests.conftest import RecordingEmailBackend, register_verified_user
from tests.import_export.helpers import create_category, create_expense
from tests.notifications.fakes import RecordingEmailProvider

CREDENTIALS = {"email": "delete.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "delete_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


async def test_delete_user_with_correct_password_succeeds(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.request(
        "DELETE",
        "/api/users/delete-user",
        json={"current_password": CREDENTIALS["password"]},
    )
    assert response.status_code == 200

    login_after_delete = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    assert login_after_delete.status_code == 401
    assert login_after_delete.json()["error_code"] == "INVALID_CREDENTIALS"


async def test_delete_user_with_wrong_password_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.request(
        "DELETE",
        "/api/users/delete-user",
        json={"current_password": "WrongPassword1!"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"

    login_still_works = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    assert login_still_works.status_code == 200


async def test_delete_user_requires_authentication(client: AsyncClient) -> None:
    response = await client.request(
        "DELETE",
        "/api/users/delete-user",
        json={"current_password": "whatever"},
    )
    assert response.status_code == 401


async def test_delete_user_emails_expense_data_export_before_deleting(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    food_id = await create_category(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Groceries",
        amount="45.00",
        spent_at="2026-01-15T12:00:00+05:30",
    )

    response = await client.request(
        "DELETE",
        "/api/users/delete-user",
        json={"current_password": CREDENTIALS["password"]},
    )
    assert response.status_code == 200, response.text

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


async def test_delete_user_is_blocked_when_export_email_fails(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    from src.app import app as fastapi_app

    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

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
        response = await client.request(
            "DELETE",
            "/api/users/delete-user",
            json={"current_password": CREDENTIALS["password"]},
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "ACCOUNT_DATA_EXPORT_FAILED"
    finally:
        fastapi_app.dependency_overrides.pop(get_email_delivery_service, None)

    # The account must still exist — deletion must not have proceeded.
    login_response = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    assert login_response.status_code == 200
