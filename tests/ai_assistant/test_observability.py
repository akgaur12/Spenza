"""Integration tests for the AI assistant admin observability endpoints:
system-wide overview, usage-over-time buckets, provider/model breakdown,
and the per-user usage table.
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_assistant.conftest import InstallFakeModel
from tests.ai_assistant.fakes import FakeChatModel, FakeTurn
from tests.ai_assistant.helpers import (
    TARGET_LOGIN_PAYLOAD,
    TARGET_SIGNUP_PAYLOAD,
    USER_A,
    USER_A_SIGNUP,
    login_as_admin,
    login_as_target,
    patch_ai_assistant_permission,
    register_target,
    switch_to_admin,
    switch_to_user_a,
)
from tests.conftest import RecordingEmailBackend, register_verified_user


async def _send_one_message(
    client: AsyncClient, chat_id: str, install_fake_model: InstallFakeModel, text: str = "ok"
) -> None:
    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=[text])]))
    response = await client.post(f"/api/v1/chats/{chat_id}/messages", json={"message": "hi"})
    assert response.status_code == 200, response.text


async def test_overview_and_provider_usage_sum_reported_tokens(
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
    install_fake_model(
        FakeChatModel(
            turns=[
                FakeTurn(
                    text_chunks=["ok"],
                    usage={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                )
            ]
        )
    )
    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "hi"})
    assert response.status_code == 200, response.text

    await switch_to_admin(client)

    overview = (await client.get("/api/v1/admin/ai-assistant/overview")).json()["data"]
    assert overview["total_input_tokens"] == 10
    assert overview["total_output_tokens"] == 4
    assert overview["average_latency_ms"] is not None

    providers = (await client.get("/api/v1/admin/ai-assistant/providers")).json()["data"][
        "providers"
    ]
    row = next(p for p in providers if p["provider"] == chat["provider"])
    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 4


async def test_estimated_cost_uses_the_static_price_table_for_a_priced_model(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    """`groq/openai-gpt-oss-120b` is priced at $0.15 in / $0.60 out per
    million tokens in `src/config/ai_model_pricing.json` — 1M of each
    should cost exactly $0.75, and that figure should show up everywhere
    cost is surfaced (overview, provider breakdown, timeseries, per-user).
    """
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(
        client, target_id, enabled=True, max_messages_per_minute=100
    )

    await login_as_target(client)
    chat = (
        await client.post(
            "/api/v1/chats", json={"provider": "groq", "model": "openai/gpt-oss-120b"}
        )
    ).json()["data"]
    install_fake_model(
        FakeChatModel(
            turns=[
                FakeTurn(
                    text_chunks=["ok"],
                    usage={
                        "input_tokens": 1_000_000,
                        "output_tokens": 1_000_000,
                        "total_tokens": 2_000_000,
                    },
                )
            ]
        )
    )
    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "hi"})
    assert response.status_code == 200, response.text

    await switch_to_admin(client)

    overview = (await client.get("/api/v1/admin/ai-assistant/overview")).json()["data"]
    assert overview["total_estimated_cost_usd"] == "0.75"

    providers = (await client.get("/api/v1/admin/ai-assistant/providers")).json()["data"]
    assert providers["total_estimated_cost_usd"] == "0.75"
    row = next(p for p in providers["providers"] if p["model"] == "openai/gpt-oss-120b")
    assert row["estimated_cost_usd"] == "0.75"

    timeseries = (
        await client.get(
            "/api/v1/admin/ai-assistant/usage/timeseries", params={"interval": "daily"}
        )
    ).json()["data"]
    bucket_costs = [b["estimated_cost_usd"] for b in timeseries["data"] if b["messages_sent"] > 0]
    assert bucket_costs == ["0.75"]

    users = (await client.get("/api/v1/admin/ai-assistant/users")).json()["data"]["items"]
    user_row = next(u for u in users if u["user_id"] == target_id)
    assert user_row["estimated_cost_usd"] == "0.75"


async def test_estimated_cost_is_null_for_a_model_with_no_published_price(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    """`groq/compound` has `pricing_available: false` in the price table
    (it's a pass-through agentic system, not one flat rate) — cost must
    stay `null` even though tokens were reported, never a guessed number.
    """
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(
        client, target_id, enabled=True, max_messages_per_minute=100
    )

    await login_as_target(client)
    chat = (
        await client.post("/api/v1/chats", json={"provider": "groq", "model": "groq/compound"})
    ).json()["data"]
    install_fake_model(
        FakeChatModel(
            turns=[
                FakeTurn(
                    text_chunks=["ok"],
                    usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                )
            ]
        )
    )
    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "hi"})
    assert response.status_code == 200, response.text

    await switch_to_admin(client)

    overview = (await client.get("/api/v1/admin/ai-assistant/overview")).json()["data"]
    assert overview["total_estimated_cost_usd"] is None

    providers = (await client.get("/api/v1/admin/ai-assistant/providers")).json()["data"]
    assert providers["total_estimated_cost_usd"] is None
    row = next(p for p in providers["providers"] if p["model"] == "groq/compound")
    assert row["estimated_cost_usd"] is None
    assert row["input_tokens"] == 100  # tokens are still tracked even without a price


async def test_endpoints_require_admin_role(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, TARGET_SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=TARGET_LOGIN_PAYLOAD)

    for path in (
        "/api/v1/admin/ai-assistant/overview",
        "/api/v1/admin/ai-assistant/usage/timeseries",
        "/api/v1/admin/ai-assistant/providers",
        "/api/v1/admin/ai-assistant/users",
    ):
        response = await client.get(path)
        assert response.status_code == 403, (path, response.text)
        assert response.json()["error_code"] == "ADMIN_PRIVILEGES_REQUIRED"


async def test_overview_reflects_activity(
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
    await _send_one_message(client, chat["id"], install_fake_model)

    await switch_to_admin(client)
    response = await client.get("/api/v1/admin/ai-assistant/overview")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total_chats"] >= 1
    assert data["total_messages_sent"] >= 1
    assert data["total_runs"] >= 1
    assert data["runs_by_status"]["completed"] >= 1
    assert data["runs_last_7_days"] >= 1
    assert data["messages_sent_last_7_days"] >= 1
    assert data["active_users_last_7_days"] >= 1
    assert data["users_with_access_enabled"] >= 1
    assert data["total_tool_calls"] >= 0


async def test_overview_with_no_activity_returns_zeros(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)

    response = await client.get("/api/v1/admin/ai-assistant/overview")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total_chats"] == 0
    assert data["total_messages_sent"] == 0
    assert data["total_runs"] == 0
    assert data["runs_by_status"] == {
        "queued": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert data["total_input_tokens"] is None
    assert data["total_output_tokens"] is None
    assert data["total_tool_calls"] == 0
    assert data["average_latency_ms"] is None


async def test_usage_timeseries_daily_buckets_activity(
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
    await _send_one_message(client, chat["id"], install_fake_model)

    await switch_to_admin(client)
    response = await client.get(
        "/api/v1/admin/ai-assistant/usage/timeseries", params={"interval": "daily"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["interval"] == "daily"
    assert data["data"], "expected at least one bucket in the default (current-month) range"
    total_messages = sum(bucket["messages_sent"] for bucket in data["data"])
    total_completed = sum(bucket["runs_completed"] for bucket in data["data"])
    assert total_messages >= 1
    assert total_completed >= 1


async def test_usage_timeseries_respects_explicit_date_range(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)

    response = await client.get(
        "/api/v1/admin/ai-assistant/usage/timeseries",
        params={"interval": "monthly", "start_date": "2020-01-01", "end_date": "2020-03-31"},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["start_date"] == "2020-01-01"
    assert data["end_date"] == "2020-03-31"
    periods = [bucket["period"] for bucket in data["data"]]
    assert periods == ["2020-01", "2020-02", "2020-03"]
    assert all(bucket["messages_sent"] == 0 for bucket in data["data"])


async def test_usage_timeseries_weekly_and_yearly_bucket_formats(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)

    weekly = await client.get(
        "/api/v1/admin/ai-assistant/usage/timeseries",
        params={"interval": "weekly", "start_date": "2020-01-01", "end_date": "2020-01-14"},
    )
    assert weekly.status_code == 200, weekly.text
    weekly_periods = [bucket["period"] for bucket in weekly.json()["data"]["data"]]
    assert all(period.startswith("2020-W") for period in weekly_periods)
    assert all(bucket["end_date"] is not None for bucket in weekly.json()["data"]["data"])

    yearly = await client.get(
        "/api/v1/admin/ai-assistant/usage/timeseries",
        params={"interval": "yearly", "start_date": "2019-06-01", "end_date": "2020-06-01"},
    )
    assert yearly.status_code == 200, yearly.text
    yearly_periods = [bucket["period"] for bucket in yearly.json()["data"]["data"]]
    assert yearly_periods == ["2019", "2020"]


async def test_provider_usage_groups_by_provider_and_model(
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
    await _send_one_message(client, chat["id"], install_fake_model)

    await switch_to_admin(client)
    response = await client.get("/api/v1/admin/ai-assistant/providers")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["providers"], "expected at least one provider/model group"
    row = data["providers"][0]
    assert row["provider"] == chat["provider"]
    assert row["model"] == chat["model"]
    assert row["total_runs"] >= 1
    assert row["completed"] >= 1


async def test_user_usage_lists_only_users_with_activity_and_supports_sorting(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
    install_fake_model: InstallFakeModel,
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)

    # Admin has no chats — shouldn't appear. Target has one chat + one
    # message, so should be the only row.
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(
        client, target_id, enabled=True, max_messages_per_minute=100
    )

    await login_as_target(client)
    chat = (await client.post("/api/v1/chats", json={})).json()["data"]
    await _send_one_message(client, chat["id"], install_fake_model)

    await switch_to_admin(client)
    response = await client.get(
        "/api/v1/admin/ai-assistant/users", params={"sort_by": "messages_sent", "order": "desc"}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["total"] == 1
    row = data["items"][0]
    assert row["user_id"] == target_id
    assert row["enabled"] is True
    assert row["total_chats"] == 1
    assert row["total_messages_sent"] == 1
    assert row["messages_sent_last_30_days"] == 1
    assert row["last_active_at"] is not None


async def test_user_usage_pagination(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_as_admin(client, email_backend, db_session_factory)
    target_id = await register_target(client, email_backend)
    await patch_ai_assistant_permission(client, target_id, enabled=True)

    await login_as_target(client)
    await client.post("/api/v1/chats", json={})

    await switch_to_admin(client)
    response = await client.get(
        "/api/v1/admin/ai-assistant/users", params={"page": 1, "page_size": 1}
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["page"] == 1
    assert data["page_size"] == 1
    assert len(data["items"]) == 1


async def test_user_id_filter_scopes_all_endpoints_to_a_single_user(
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

    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    list_response = await client.get("/api/v1/admin/users")
    assert list_response.status_code == 200, list_response.text
    items = list_response.json()["data"]["items"]
    user_a_id = next(u for u in items if u["email"] == USER_A["email"])["id"]
    await patch_ai_assistant_permission(
        client, user_a_id, enabled=True, max_messages_per_minute=100
    )

    await login_as_target(client)
    target_chat = (await client.post("/api/v1/chats", json={})).json()["data"]
    install_fake_model(
        FakeChatModel(
            turns=[
                FakeTurn(
                    text_chunks=["ok"],
                    usage={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                )
            ]
        )
    )
    response = await client.post(
        f"/api/v1/chats/{target_chat['id']}/messages", json={"message": "hi"}
    )
    assert response.status_code == 200, response.text

    await switch_to_user_a(client)
    user_a_chat = (await client.post("/api/v1/chats", json={})).json()["data"]
    install_fake_model(
        FakeChatModel(
            turns=[
                FakeTurn(
                    text_chunks=["ok"],
                    usage={"input_tokens": 20, "output_tokens": 8, "total_tokens": 28},
                )
            ]
        )
    )
    response = await client.post(
        f"/api/v1/chats/{user_a_chat['id']}/messages", json={"message": "hi"}
    )
    assert response.status_code == 200, response.text

    await switch_to_admin(client)

    # Overview: scoped vs. system-wide totals.
    target_overview = (
        await client.get("/api/v1/admin/ai-assistant/overview", params={"user_id": target_id})
    ).json()["data"]
    assert target_overview["total_chats"] == 1
    assert target_overview["total_messages_sent"] == 1
    assert target_overview["total_input_tokens"] == 10
    assert target_overview["total_output_tokens"] == 4

    user_a_overview = (
        await client.get("/api/v1/admin/ai-assistant/overview", params={"user_id": user_a_id})
    ).json()["data"]
    assert user_a_overview["total_chats"] == 1
    assert user_a_overview["total_messages_sent"] == 1
    assert user_a_overview["total_input_tokens"] == 20
    assert user_a_overview["total_output_tokens"] == 8

    system_overview = (await client.get("/api/v1/admin/ai-assistant/overview")).json()["data"]
    assert system_overview["total_chats"] == 2
    assert system_overview["total_messages_sent"] == 2
    assert system_overview["total_input_tokens"] == 30
    assert system_overview["total_output_tokens"] == 12

    # Usage timeseries: scoped message counts.
    target_timeseries = (
        await client.get(
            "/api/v1/admin/ai-assistant/usage/timeseries",
            params={"interval": "daily", "user_id": target_id},
        )
    ).json()["data"]
    assert sum(b["messages_sent"] for b in target_timeseries["data"]) == 1

    system_timeseries = (
        await client.get(
            "/api/v1/admin/ai-assistant/usage/timeseries", params={"interval": "daily"}
        )
    ).json()["data"]
    assert sum(b["messages_sent"] for b in system_timeseries["data"]) == 2

    # Provider/model breakdown: scoped vs. combined token totals.
    target_providers = (
        await client.get("/api/v1/admin/ai-assistant/providers", params={"user_id": target_id})
    ).json()["data"]["providers"]
    target_row = next(p for p in target_providers if p["provider"] == target_chat["provider"])
    assert target_row["total_runs"] == 1
    assert target_row["input_tokens"] == 10

    system_providers = (await client.get("/api/v1/admin/ai-assistant/providers")).json()["data"][
        "providers"
    ]
    system_row = next(p for p in system_providers if p["provider"] == target_chat["provider"])
    assert system_row["total_runs"] == 2
    assert system_row["input_tokens"] == 30

    # Per-user usage table: scoped to exactly one row.
    target_users = (
        await client.get("/api/v1/admin/ai-assistant/users", params={"user_id": target_id})
    ).json()["data"]
    assert target_users["total"] == 1
    assert target_users["items"][0]["user_id"] == target_id

    system_users = (await client.get("/api/v1/admin/ai-assistant/users")).json()["data"]
    assert system_users["total"] == 2
