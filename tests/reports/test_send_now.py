"""Integration tests for `POST /api/v1/reports/send-now`.

Uses the real `ConsoleEmailProvider` for the happy path (never raises, so
delivery always succeeds) and an injected always-failing
`RecordingEmailProvider` (via a dependency override) for the failure path.
"""

from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, category_id_by_name, create_expense, login_user_a
from tests.notifications.fakes import RecordingEmailProvider
from tests.notifications.helpers import list_notifications


async def test_send_report_now_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/reports/send-now", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 401


async def test_send_report_now_emails_the_report_and_returns_ok(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Groceries",
        amount="45.00",
        spent_at="2026-07-05T12:00:00+05:30",
    )

    response = await client.post(
        "/api/v1/reports/send-now", json={"type": "monthly", "year": 2026, "month": 7}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["sent_to"] == USER_A["email"]
    assert data["filename"] == "monthly-report-2026-07.pdf"


async def test_send_report_now_creates_a_report_ready_notification(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post("/api/v1/reports/send-now", json={"type": "yearly", "year": 2025})
    assert response.status_code == 200, response.text

    notifications = await list_notifications(client)
    assert notifications["total"] == 1
    assert notifications["items"][0]["type"] == "report_ready"
    assert "2025" in notifications["items"][0]["title"]


async def test_send_report_now_rejects_future_periods(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.post("/api/v1/reports/send-now", json={"type": "yearly", "year": 2099})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_REPORT_YEAR"


async def test_send_report_now_returns_503_when_delivery_fails(
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
        response = await client.post(
            "/api/v1/reports/send-now", json={"type": "yearly", "year": 2025}
        )
        assert response.status_code == 503
        assert response.json()["error_code"] == "REPORT_EMAIL_DELIVERY_FAILED"
    finally:
        fastapi_app.dependency_overrides.pop(get_email_delivery_service, None)
