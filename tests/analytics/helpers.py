"""Shared test helpers for the `analytics` test package."""

from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

USER_A = {"email": "user.a@example.com", "password": "SecureP@ss1"}
USER_A_SIGNUP = {**USER_A, "username": "user_a"}
USER_A_LOGIN = {"identifier": USER_A["email"], "password": USER_A["password"]}

USER_B = {"email": "user.b@example.com", "password": "SecureP@ss1"}
USER_B_SIGNUP = {**USER_B, "username": "user_b"}
USER_B_LOGIN = {"identifier": USER_B["email"], "password": USER_B["password"]}


async def login_user_a(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def login_user_b(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_B_SIGNUP)
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text


async def switch_to_user_a(client: AsyncClient) -> None:
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def category_id_by_name(client: AsyncClient, name: str) -> str:
    response = await client.get("/api/v1/categories")
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    category_id: str = next(i for i in items if i["name"] == name)["id"]
    return category_id


async def create_category(client: AsyncClient, name: str, icon: str | None = None) -> str:
    payload: dict[str, object] = {"name": name}
    if icon is not None:
        payload["icon"] = icon
    response = await client.post("/api/v1/categories", json=payload)
    assert response.status_code == 201, response.text
    category_id: str = response.json()["data"]["id"]
    return category_id


async def create_expense(
    client: AsyncClient,
    *,
    category_id: str,
    spent_at: datetime,
    description: str = "Expense",
    amount: str = "100.00",
) -> dict[str, Any]:
    # Sent pre-converted to UTC: the test suite's SQLite database silently
    # drops any non-UTC offset on read instead of converting it (PostgreSQL
    # handles any offset correctly), so tests must submit `spent_at` values
    # that are already UTC to get deterministic bucketing.
    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": category_id,
            "description": description,
            "amount": amount,
            "spent_at": spent_at.astimezone(UTC).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def get_category_analytics(client: AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/api/v1/analytics/categories", params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def get_trend_analytics(client: AsyncClient, **params: str) -> dict[str, Any]:
    response = await client.get("/api/v1/analytics/trends", params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def get_calendar_heatmap(client: AsyncClient, **params: str | int) -> dict[str, Any]:
    response = await client.get("/api/v1/analytics/calendar-heatmap", params=params)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data
