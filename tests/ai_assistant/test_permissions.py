"""Integration tests for per-user AI assistant access control and usage
limits: the admin endpoints, the `/me` status exposed to the owning user,
and enforcement (403 when disabled, 429 for each of the 5 distinct limit
types) on `POST /chats` and `POST /chats/{id}/messages`.

Every test here explicitly creates its own `AIAssistantPermission` state
(via the admin PATCH endpoint) rather than relying on the suite-wide
"enabled by default" fixture in `conftest.py` — that fixture only changes
what "no row yet" resolves to, so a test that always sets an explicit row
is unaffected by it either way, except where a test is specifically about
the real "no row yet" default, which restores it via its own `monkeypatch`
(layering on top of the fixture's, and unwinding first).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.modules.ai_assistant.permissions.service as permissions_service
from src.core.app_config import settings
from tests.ai_assistant.conftest import InstallFakeModel
from tests.ai_assistant.fakes import FakeChatModel, FakeTurn
from tests.ai_assistant.helpers import (
    TARGET_LOGIN_PAYLOAD,
    TARGET_SIGNUP_PAYLOAD,
    login_as_admin,
    login_as_target,
    patch_ai_assistant_permission,
    register_target,
    switch_to_admin,
)
from tests.conftest import RecordingEmailBackend, register_verified_user


@pytest.fixture
def _real_default_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restores the real production default (`enabled=False` for a user
    with no permission row) for tests specifically about that default —
    overrides the suite-wide `_ai_assistant_access_enabled_by_default`
    fixture, which layered on top of this call and unwinds first.
    """
    monkeypatch.setattr(permissions_service, "_DEFAULT_ENABLED", False)


# ── Admin endpoints ───────────────────────────────────────────────────────


@pytest.mark.usefixtures("_real_default_disabled")
async def test_admin_get_returns_disabled_defaults_when_no_row(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)

    response = await client.get(f"/api/v1/admin/users/{target_id}/ai-assistant")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["enabled"] is False
    assert data["max_messages_per_minute"] is None
    assert data["max_messages_per_day"] is None
    assert data["max_messages_per_month"] is None
    assert data["max_new_chats_per_day"] is None
    assert data["max_new_chats_per_month"] is None
    assert data["messages_sent_today"] == 0
    assert data["chats_created_today"] == 0


async def test_admin_patch_enables_and_sets_limits(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)

    data = await patch_ai_assistant_permission(
        client,
        target_id,
        enabled=True,
        max_messages_per_minute=5,
        max_messages_per_day=100,
        max_new_chats_per_day=10,
    )

    assert data["enabled"] is True
    assert data["max_messages_per_minute"] == 5
    assert data["max_messages_per_day"] == 100
    assert data["max_new_chats_per_day"] == 10
    assert data["max_messages_per_month"] is None  # untouched field stays unset

    # A later partial PATCH only touches the fields it sends.
    data = await patch_ai_assistant_permission(client, target_id, max_messages_per_day=50)
    assert data["max_messages_per_day"] == 50
    assert data["enabled"] is True  # unaffected by the partial update
    assert data["max_messages_per_minute"] == 5


async def test_admin_patch_explicit_null_clears_a_limit(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(client, target_id, enabled=True, max_messages_per_day=100)

    data = await patch_ai_assistant_permission(client, target_id, max_messages_per_day=None)

    assert data["max_messages_per_day"] is None
    assert data["enabled"] is True


async def test_admin_endpoints_require_admin_role(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, TARGET_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=TARGET_LOGIN_PAYLOAD)

    response = await client.get(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/ai-assistant"
    )

    assert response.status_code == 403, response.text
    assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_admin_endpoints_404_for_nonexistent_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)

    get_response = await client.get(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/ai-assistant"
    )
    assert get_response.status_code == 404, get_response.text

    patch_response = await client.patch(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000/ai-assistant",
        json={"enabled": True},
    )
    assert patch_response.status_code == 404, patch_response.text


# ── `/me` status ──────────────────────────────────────────────────────────


@pytest.mark.usefixtures("_real_default_disabled")
async def test_me_reflects_disabled_default_and_admin_changes(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)

    await login_as_target(client)
    me_response = await client.get("/api/users/me")
    assert me_response.status_code == 200, me_response.text
    ai_status = me_response.json()["data"]["ai_assistant"]
    assert ai_status["enabled"] is False
    assert "max_messages_per_minute" not in ai_status  # never exposed to the end user

    await switch_to_admin(client)
    await patch_ai_assistant_permission(client, target_id, enabled=True, max_new_chats_per_day=7)

    await login_as_target(client)
    me_response = await client.get("/api/users/me")
    ai_status = me_response.json()["data"]["ai_assistant"]
    assert ai_status["enabled"] is True
    assert ai_status["max_new_chats_per_day"] == 7


# ── Enforcement: disabled ─────────────────────────────────────────────────


@pytest.mark.usefixtures("_real_default_disabled")
async def test_disabled_user_cannot_create_chat_or_send_message_but_keeps_history(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(client, target_id, enabled=True)

    await login_as_target(client)
    create_response = await client.post("/api/v1/chats", json={"title": "Before disabling"})
    assert create_response.status_code == 201, create_response.text
    chat_id = create_response.json()["data"]["id"]

    await switch_to_admin(client)
    await patch_ai_assistant_permission(client, target_id, enabled=False)

    await login_as_target(client)
    blocked_create = await client.post("/api/v1/chats", json={})
    assert blocked_create.status_code == 403, blocked_create.text
    assert blocked_create.json()["error_code"] == "AI_ASSISTANT_DISABLED"

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["hi"])]))
    blocked_message = await client.post(
        f"/api/v1/chats/{chat_id}/messages", json={"message": "Hello"}
    )
    assert blocked_message.status_code == 403, blocked_message.text
    assert blocked_message.json()["error_code"] == "AI_ASSISTANT_DISABLED"

    # Existing chats stay fully readable/renameable/deletable while disabled.
    get_response = await client.get(f"/api/v1/chats/{chat_id}")
    assert get_response.status_code == 200
    rename_response = await client.patch(f"/api/v1/chats/{chat_id}", json={"title": "Still mine"})
    assert rename_response.status_code == 200
    delete_response = await client.delete(f"/api/v1/chats/{chat_id}")
    assert delete_response.status_code == 204


# ── Enforcement: new-chat limits ──────────────────────────────────────────


async def test_daily_new_chat_limit_exceeded(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(client, target_id, enabled=True, max_new_chats_per_day=1)

    await login_as_target(client)
    first = await client.post("/api/v1/chats", json={})
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/chats", json={})
    assert second.status_code == 429, second.text
    assert second.json()["error_code"] == "AI_CHAT_DAILY_CHAT_LIMIT_EXCEEDED"


async def test_monthly_new_chat_limit_exceeded(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(
        client, target_id, enabled=True, max_new_chats_per_day=None, max_new_chats_per_month=1
    )

    await login_as_target(client)
    first = await client.post("/api/v1/chats", json={})
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/chats", json={})
    assert second.status_code == 429, second.text
    assert second.json()["error_code"] == "AI_CHAT_MONTHLY_CHAT_LIMIT_EXCEEDED"


# ── Enforcement: message limits ───────────────────────────────────────────


async def test_per_minute_message_limit_falls_back_to_global_default_when_unset(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AI_CHAT_REQUESTS_PER_MINUTE", 1)

    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(client, target_id, enabled=True)  # per-minute left unset

    await login_as_target(client)
    chat = (await client.post("/api/v1/chats", json={})).json()["data"]

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    first = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "one"})
    assert first.status_code == 200, first.text

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    second = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "two"})
    assert second.status_code == 429, second.text
    assert second.json()["error_code"] == "AI_CHAT_RATE_LIMITED"


async def test_per_minute_message_limit_uses_per_user_override(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    # Global default left generous; the per-user override is the binding one.
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(client, target_id, enabled=True, max_messages_per_minute=1)

    await login_as_target(client)
    chat = (await client.post("/api/v1/chats", json={})).json()["data"]

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    first = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "one"})
    assert first.status_code == 200, first.text

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    second = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "two"})
    assert second.status_code == 429, second.text
    assert second.json()["error_code"] == "AI_CHAT_RATE_LIMITED"


async def test_daily_message_limit_exceeded(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    # A generous per-minute ceiling isolates the daily limit being tested.
    await patch_ai_assistant_permission(
        client, target_id, enabled=True, max_messages_per_minute=100, max_messages_per_day=1
    )

    await login_as_target(client)
    chat = (await client.post("/api/v1/chats", json={})).json()["data"]

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    first = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "one"})
    assert first.status_code == 200, first.text

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    second = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "two"})
    assert second.status_code == 429, second.text
    assert second.json()["error_code"] == "AI_CHAT_DAILY_LIMIT_EXCEEDED"


async def test_monthly_message_limit_exceeded(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(
        client,
        target_id,
        enabled=True,
        max_messages_per_minute=100,
        max_messages_per_day=None,
        max_messages_per_month=1,
    )

    await login_as_target(client)
    chat = (await client.post("/api/v1/chats", json={})).json()["data"]

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    first = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "one"})
    assert first.status_code == 200, first.text

    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    second = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "two"})
    assert second.status_code == 429, second.text
    assert second.json()["error_code"] == "AI_CHAT_MONTHLY_LIMIT_EXCEEDED"


async def test_usage_counts_reflect_sent_messages_and_created_chats(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(
        client, target_id, enabled=True, max_messages_per_minute=100
    )

    await login_as_target(client)
    chat = (await client.post("/api/v1/chats", json={})).json()["data"]
    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["ok"])]))
    await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "hi"})

    await switch_to_admin(client)
    response = await client.get(f"/api/v1/admin/users/{target_id}/ai-assistant")
    data = response.json()["data"]
    assert data["messages_sent_today"] == 1
    assert data["messages_sent_this_month"] == 1
    assert data["chats_created_today"] == 1
    assert data["chats_created_this_month"] == 1
