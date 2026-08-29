"""Shared test helpers for the `ai_assistant` test package."""

import json
from datetime import datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.users.models import User
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend, promote_to_admin, register_verified_user

USER_A = {"email": "user.a@example.com", "password": "SecureP@ss1"}
USER_A_SIGNUP = {**USER_A, "username": "user_a"}
USER_A_LOGIN = {"identifier": USER_A["email"], "password": USER_A["password"]}

USER_B = {"email": "user.b@example.com", "password": "SecureP@ss1"}
USER_B_SIGNUP = {**USER_B, "username": "user_b"}
USER_B_LOGIN = {"identifier": USER_B["email"], "password": USER_B["password"]}

# Used by every test that needs an admin session plus a distinct
# non-admin "target" user to act on (permission tests, observability
# tests) — kept here rather than duplicated per test file.
ADMIN_CREDENTIALS = {"email": "admin@example.com", "password": "SecureP@ss1"}
ADMIN_SIGNUP_PAYLOAD = {**ADMIN_CREDENTIALS, "username": "admin_user"}
ADMIN_LOGIN_PAYLOAD = {
    "identifier": ADMIN_CREDENTIALS["email"],
    "password": ADMIN_CREDENTIALS["password"],
}

TARGET_CREDENTIALS = {"email": "target.user@example.com", "password": "SecureP@ss1"}
TARGET_SIGNUP_PAYLOAD = {**TARGET_CREDENTIALS, "username": "target_user"}
TARGET_LOGIN_PAYLOAD = {
    "identifier": TARGET_CREDENTIALS["email"],
    "password": TARGET_CREDENTIALS["password"],
}


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


async def get_user(session: AsyncSession, email: str) -> User:
    user = await UserRepository(session).get_by_email(email)
    assert user is not None, f"No user found with email {email}"
    return user


async def login_as_admin(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await register_verified_user(client, email_backend, ADMIN_SIGNUP_PAYLOAD)
    await promote_to_admin(db_session_factory, ADMIN_CREDENTIALS["email"])
    response = await client.post("/api/users/login", json=ADMIN_LOGIN_PAYLOAD)
    assert response.status_code == 200, response.text


async def switch_to_admin(client: AsyncClient) -> None:
    """Re-authenticates as the already-registered admin — use this (not
    `login_as_admin`) to switch back to the admin session later in a test
    that already called `login_as_admin` once.
    """
    response = await client.post("/api/users/login", json=ADMIN_LOGIN_PAYLOAD)
    assert response.status_code == 200, response.text


async def register_target(client: AsyncClient, email_backend: RecordingEmailBackend) -> str:
    """Registers the target (non-admin) user and returns their id, using
    whichever session is currently authenticated on `client` to look them
    up via the admin list endpoint — so the caller must already be logged
    in as an admin.
    """
    await register_verified_user(client, email_backend, TARGET_SIGNUP_PAYLOAD)
    list_response = await client.get("/api/v1/admin/users")
    assert list_response.status_code == 200, list_response.text
    items = list_response.json()["data"]["items"]
    target = next(u for u in items if u["email"] == TARGET_CREDENTIALS["email"])
    target_id: str = target["id"]
    return target_id


async def login_as_target(client: AsyncClient) -> None:
    response = await client.post("/api/users/login", json=TARGET_LOGIN_PAYLOAD)
    assert response.status_code == 200, response.text


async def patch_ai_assistant_permission(
    client: AsyncClient, user_id: str, **body: object
) -> dict[str, object]:
    response = await client.patch(f"/api/v1/admin/users/{user_id}/ai-assistant", json=body)
    assert response.status_code == 200, response.text
    data: dict[str, object] = response.json()["data"]
    return data


async def category_id_by_name(client: AsyncClient, name: str) -> str:
    response = await client.get("/api/v1/categories")
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    category_id: str = next(i for i in items if i["name"] == name)["id"]
    return category_id


async def create_expense(
    client: AsyncClient,
    *,
    category_id: str,
    spent_at: datetime,
    description: str = "Expense",
    amount: str | Decimal = "100.00",
) -> str:
    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": category_id,
            "description": description,
            "amount": str(amount),
            "spent_at": spent_at.isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    expense_id: str = response.json()["data"]["id"]
    return expense_id


async def create_recurring_expense(
    client: AsyncClient,
    *,
    category_id: str,
    start_date: str,
    frequency: str = "monthly",
    description: str = "Subscription",
    amount: str | Decimal = "199.00",
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/recurring-expenses",
        json={
            "category_id": category_id,
            "description": description,
            "amount": str(amount),
            "frequency": frequency,
            "start_date": start_date,
        },
    )
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()["data"]
    return data


async def create_chat(
    client: AsyncClient,
    *,
    title: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if title is not None:
        payload["title"] = title
    if provider is not None:
        payload["provider"] = provider
    if model is not None:
        payload["model"] = model
    response = await client.post("/api/v1/chats", json=payload)
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()["data"]
    return data


def parse_sse(text: str) -> list[tuple[str, dict[str, object]]]:
    """Parse a raw `text/event-stream` body into `(event, data)` pairs, in
    order — mirrors what a real SSE client would see.
    """
    events: list[tuple[str, dict[str, object]]] = []
    event_name: str | None = None
    for line in text.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            assert event_name is not None, "data line with no preceding event line"
            events.append((event_name, json.loads(line.removeprefix("data: "))))
            event_name = None
    return events
