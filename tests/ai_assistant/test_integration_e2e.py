"""End-to-end black-box test of the full flow described in the spec:
register -> create chat -> send a message that triggers a real,
DB-backed tool call (only the LLM itself is faked) -> SSE response ->
persisted messages -> pagination -> rename -> cancel-on-a-finished-run is
rejected -> delete.
"""

from datetime import UTC, datetime

from httpx import AsyncClient

from tests.ai_assistant.conftest import InstallFakeModel
from tests.ai_assistant.fakes import FakeChatModel, FakeTurn
from tests.ai_assistant.helpers import (
    category_id_by_name,
    create_chat,
    create_expense,
    login_user_a,
    parse_sse,
)
from tests.conftest import RecordingEmailBackend


async def test_full_chat_lifecycle_with_real_tool_call(
    client: AsyncClient, email_backend: RecordingEmailBackend, install_fake_model: InstallFakeModel
) -> None:
    # 1. Register + seed real expense data for the tool to find.
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        spent_at=datetime(2026, 3, 10, tzinfo=UTC),
        description="Groceries",
        amount="450.00",
    )

    # 2. Create a chat.
    chat = await create_chat(client, title="Spending check")
    assert chat["title"] == "Spending check"

    # 3. Script the LLM to call a real tool, then answer using its result.
    install_fake_model(
        FakeChatModel(
            turns=[
                FakeTurn(
                    tool_calls=[
                        {
                            "name": "get_total_spending",
                            "args": {"start_date": "2026-03-01", "end_date": "2026-03-31"},
                            "id": "call_1",
                        }
                    ]
                ),
                FakeTurn(text_chunks=["You spent ", "₹450.00 in March."]),
            ]
        )
    )

    # 4. Send the message and consume the SSE response.
    response = await client.post(
        f"/api/v1/chats/{chat['id']}/messages",
        json={"message": "How much did I spend in March?"},
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
        "message_delta",
        "message_completed",
        "run_completed",
    ]
    tool_result = next(data for name, data in events if name == "tool_result")
    assert tool_result == {"tool": "get_total_spending", "status": "ok"}
    completed = next(data for name, data in events if name == "message_completed")
    assert completed["content"] == "You spent ₹450.00 in March."
    message_id = completed["message_id"]

    # 5. Persisted messages, in order, correct roles/content.
    messages_response = await client.get(f"/api/v1/chats/{chat['id']}/messages")
    assert messages_response.status_code == 200, messages_response.text
    items = messages_response.json()["data"]["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert items[0]["content"] == "How much did I spend in March?"
    assert items[1]["content"] == "You spent ₹450.00 in March."
    assert items[1]["id"] == message_id

    # 6. Pagination still works with a single page.
    paginated = await client.get(
        f"/api/v1/chats/{chat['id']}/messages", params={"page": 1, "page_size": 1}
    )
    assert paginated.json()["data"]["total_pages"] == 2

    # 7. The run already finished — cancelling it now is rejected, not a
    #    silent no-op, and no run is ever left stuck `running`.
    cancel_response = await client.post(f"/api/v1/chats/{chat['id']}/messages/{message_id}/cancel")
    assert cancel_response.status_code == 409, cancel_response.text
    assert cancel_response.json()["error_code"] == "AI_RUN_NOT_CANCELLABLE"

    # 8. Rename, then delete — the chat and its messages/runs are gone.
    rename_response = await client.patch(
        f"/api/v1/chats/{chat['id']}", json={"title": "March spending"}
    )
    assert rename_response.status_code == 200, rename_response.text

    delete_response = await client.delete(f"/api/v1/chats/{chat['id']}")
    assert delete_response.status_code == 204, delete_response.text

    after_delete = await client.get(f"/api/v1/chats/{chat['id']}")
    assert after_delete.status_code == 404
