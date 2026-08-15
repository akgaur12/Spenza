"""Integration tests for GET /api/v1/admin/stats/overview."""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import RecordingEmailBackend, promote_to_admin, register_verified_user

ADMIN_CREDENTIALS = {"email": "admin.stats@example.com", "password": "SecureP@ss1"}
ADMIN_SIGNUP_PAYLOAD = {**ADMIN_CREDENTIALS, "username": "admin_stats_user"}
ADMIN_LOGIN_PAYLOAD = {
    "identifier": ADMIN_CREDENTIALS["email"],
    "password": ADMIN_CREDENTIALS["password"],
}

PLAIN_CREDENTIALS = {"email": "plain.stats@example.com", "password": "SecureP@ss1"}
PLAIN_SIGNUP_PAYLOAD = {**PLAIN_CREDENTIALS, "username": "plain_stats_user"}
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


async def test_stats_overview_requires_admin(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=PLAIN_LOGIN_PAYLOAD)

    response = await client.get("/api/v1/admin/stats/overview")

    assert response.status_code == 403
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_stats_overview_reflects_current_state(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _login_as_admin(client, email_backend, db_session_factory)
    await register_verified_user(client, email_backend, PLAIN_SIGNUP_PAYLOAD)

    category_response = await client.post(
        "/api/v1/admin/categories", json={"name": "Stats Test Category"}
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()["data"]

    create_response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": category["id"],
            "description": "Coffee",
            "amount": "150.00",
            "spent_at": "2026-08-01T00:00:00+00:00",
        },
    )
    assert create_response.status_code == 201, create_response.text

    response = await client.get("/api/v1/admin/stats/overview")

    assert response.status_code == 200, response.text
    data = response.json()["data"]

    assert data["users"]["total"] == 2
    assert data["users"]["active"] == 2
    assert data["users"]["admins"] == 1
    assert data["users"]["signups_last_7_days"] == 2

    assert data["expenses"]["total_count"] == 1
    assert data["expenses"]["total_amount"] == "150.00"

    assert data["categories"]["system_count"] >= 1
