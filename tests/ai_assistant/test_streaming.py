"""Integration tests for the exact SSE event sequence over HTTP: a plain
answer, a single tool call, and an agent-level failure.

`httpx.ASGITransport` runs the whole ASGI app call (draining the entire
`StreamingResponse` body) before returning anything to the client, so
there's no real incremental streaming to test through this harness —
these assertions are all against the full, ordered event list from one
completed response. Cancellation-mid-stream (which genuinely needs two
requests racing while the first is still in flight) is tested at the
service level in `test_agent_graph.py`, driving `ChatService.stream_run`
directly instead of through HTTP for that reason. Multiple-sequential-tool-
calls and tool-failure/timeout are also there, for the same "needs a
synthetic tool, not the real registry" reason.
"""

from httpx import AsyncClient

from tests.ai_assistant.conftest import InstallFakeModel
from tests.ai_assistant.fakes import FakeChatModel, FakeTurn
from tests.ai_assistant.helpers import create_chat, login_user_a, parse_sse
from tests.conftest import RecordingEmailBackend


async def test_simple_response_event_sequence(
    client: AsyncClient, email_backend: RecordingEmailBackend, install_fake_model: InstallFakeModel
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)
    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["All good."])]))

    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "Hi"})

    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    assert [name for name, _ in events] == [
        "run_started",
        "message_started",
        "message_delta",
        "message_completed",
        "run_completed",
    ]
    run_started_data = events[0][1]
    assert run_started_data["chat_id"] == chat["id"]
    assert events[-1][1]["status"] == "completed"


async def test_single_tool_call_event_sequence(
    client: AsyncClient, email_backend: RecordingEmailBackend, install_fake_model: InstallFakeModel
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)
    install_fake_model(
        FakeChatModel(
            turns=[
                FakeTurn(tool_calls=[{"name": "get_categories", "args": {}, "id": "call_1"}]),
                FakeTurn(text_chunks=["You have several categories."]),
            ]
        )
    )

    response = await client.post(
        f"/api/v1/chats/{chat['id']}/messages", json={"message": "What categories do I have?"}
    )

    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names == [
        "run_started",
        "message_started",
        "tool_started",
        "tool_result",
        "message_delta",
        "message_completed",
        "run_completed",
    ]
    tool_started_data = next(data for name, data in events if name == "tool_started")
    assert tool_started_data == {"tool": "get_categories"}
    tool_result_data = next(data for name, data in events if name == "tool_result")
    assert tool_result_data == {"tool": "get_categories", "status": "ok"}


async def test_agent_failure_emits_run_failed(
    client: AsyncClient, email_backend: RecordingEmailBackend, install_fake_model: InstallFakeModel
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)
    install_fake_model(FakeChatModel(turns=[FakeTurn(error=RuntimeError("provider exploded"))]))

    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "Hi"})

    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names == ["run_started", "message_started", "run_failed"]
    failed_data = events[-1][1]
    assert failed_data["status"] == "failed"
    assert "provider exploded" not in str(failed_data["error"])  # never leak raw provider errors

    messages_response = await client.get(f"/api/v1/chats/{chat['id']}/messages")
    run_response = await client.get(f"/api/v1/chats/{chat['id']}")
    assert messages_response.status_code == 200
    assert run_response.status_code == 200
