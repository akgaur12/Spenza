"""Integration tests for chat CRUD: create, list, get, rename, delete, and
ownership isolation between users.
"""

from httpx import AsyncClient

from src.core.app_config import settings
from tests.ai_assistant.helpers import (
    create_chat,
    login_user_a,
    login_user_b,
    switch_to_user_a,
)
from tests.conftest import RecordingEmailBackend


async def test_create_chat_uses_configured_defaults_when_omitted(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)

    response = await client.post("/api/v1/chats", json={})

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["title"] == "New Chat"
    # Asserted against whatever's actually configured (not a hardcoded
    # literal) — a developer's own `.env` may set a different default
    # provider/model than the code-level default.
    assert data["provider"] == settings.AI_DEFAULT_PROVIDER.value
    assert data["model"] == settings.AI_DEFAULT_MODEL
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_chat_accepts_explicit_provider_and_model(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)

    response = await client.post(
        "/api/v1/chats",
        json={"title": "July Spending", "provider": "openai", "model": "gpt-4.1-mini"},
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["title"] == "July Spending"
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4.1-mini"


async def test_list_chats_sorted_by_updated_at_desc(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    first = await create_chat(client, title="First")
    second = await create_chat(client, title="Second")

    response = await client.get("/api/v1/chats")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 2
    ids = [item["id"] for item in data["items"]]
    assert ids == [second["id"], first["id"]]
    assert all(item["message_count"] == 0 for item in data["items"])


async def test_list_chats_search_by_title(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await create_chat(client, title="Grocery spending")
    await create_chat(client, title="Travel budget")

    response = await client.get("/api/v1/chats", params={"search": "grocery"})

    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Grocery spending"


async def test_get_chat(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client, title="My Chat")

    response = await client.get(f"/api/v1/chats/{chat['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["id"] == chat["id"]


async def test_get_nonexistent_chat_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)

    response = await client.get("/api/v1/chats/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404, response.text
    assert response.json()["error_code"] == "CHAT_NOT_FOUND"


async def test_rename_chat_trims_and_validates(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)

    response = await client.patch(f"/api/v1/chats/{chat['id']}", json={"title": "  Renamed  "})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["title"] == "Renamed"


async def test_rename_chat_rejects_blank_title(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)

    response = await client.patch(f"/api/v1/chats/{chat['id']}", json={"title": "   "})

    assert response.status_code == 422, response.text


async def test_delete_chat(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)

    response = await client.delete(f"/api/v1/chats/{chat['id']}")
    assert response.status_code == 204, response.text

    get_response = await client.get(f"/api/v1/chats/{chat['id']}")
    assert get_response.status_code == 404


async def test_user_cannot_access_another_users_chat(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client, title="User A's chat")

    await login_user_b(client, email_backend)
    get_response = await client.get(f"/api/v1/chats/{chat['id']}")
    assert get_response.status_code == 404

    rename_response = await client.patch(f"/api/v1/chats/{chat['id']}", json={"title": "Hijacked"})
    assert rename_response.status_code == 404

    delete_response = await client.delete(f"/api/v1/chats/{chat['id']}")
    assert delete_response.status_code == 404

    await switch_to_user_a(client)
    still_there = await client.get(f"/api/v1/chats/{chat['id']}")
    assert still_there.status_code == 200
    assert still_there.json()["data"]["title"] == "User A's chat"


async def test_user_cannot_see_another_users_chats_in_list(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    await create_chat(client, title="User A's chat")

    await login_user_b(client, email_backend)
    response = await client.get("/api/v1/chats")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["total"] == 0
