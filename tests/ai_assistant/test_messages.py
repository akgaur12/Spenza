"""Integration tests for sending/persisting/paginating chat messages, and
ownership isolation between users.
"""

from httpx import AsyncClient

from tests.ai_assistant.conftest import InstallFakeModel
from tests.ai_assistant.fakes import FakeChatModel, FakeTurn
from tests.ai_assistant.helpers import create_chat, login_user_a, login_user_b, parse_sse
from tests.conftest import RecordingEmailBackend


async def test_send_message_persists_user_and_assistant_messages(
    client: AsyncClient, email_backend: RecordingEmailBackend, install_fake_model: InstallFakeModel
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)
    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["Hi ", "there!"])]))

    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "Hello"})

    assert response.status_code == 200, response.text
    events = parse_sse(response.text)
    event_names = [name for name, _ in events]
    assert event_names == [
        "run_started",
        "message_started",
        "message_delta",
        "message_delta",
        "message_completed",
        "run_completed",
    ]
    completed = next(data for name, data in events if name == "message_completed")
    assert completed["content"] == "Hi there!"

    list_response = await client.get(f"/api/v1/chats/{chat['id']}/messages")
    assert list_response.status_code == 200, list_response.text
    items = list_response.json()["data"]["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert items[0]["content"] == "Hello"
    assert items[1]["content"] == "Hi there!"
    assert items[0]["sequence"] < items[1]["sequence"]


async def test_send_message_rejects_blank_message(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)

    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "   "})

    assert response.status_code == 422, response.text


async def test_send_message_to_nonexistent_chat_returns_404(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)

    response = await client.post(
        "/api/v1/chats/00000000-0000-0000-0000-000000000000/messages",
        json={"message": "Hello"},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error_code"] == "CHAT_NOT_FOUND"


async def test_send_message_with_unconfigured_provider_fails_before_streaming(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client, provider="openai", model="gpt-4.1-mini")

    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "Hello"})

    assert response.status_code == 503, response.text
    assert response.json()["error_code"] == "AI_PROVIDER_UNAVAILABLE"


async def test_list_messages_pagination(
    client: AsyncClient, email_backend: RecordingEmailBackend, install_fake_model: InstallFakeModel
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)

    for i in range(3):
        install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=[f"reply {i}"])]))
        response = await client.post(
            f"/api/v1/chats/{chat['id']}/messages", json={"message": f"question {i}"}
        )
        assert response.status_code == 200, response.text

    first_page = await client.get(
        f"/api/v1/chats/{chat['id']}/messages", params={"page": 1, "page_size": 2}
    )
    assert first_page.status_code == 200, first_page.text
    data = first_page.json()["data"]
    assert data["total"] == 6
    assert data["total_pages"] == 3
    assert [item["content"] for item in data["items"]] == ["question 0", "reply 0"]

    second_page = await client.get(
        f"/api/v1/chats/{chat['id']}/messages", params={"page": 2, "page_size": 2}
    )
    assert [item["content"] for item in second_page.json()["data"]["items"]] == [
        "question 1",
        "reply 1",
    ]


async def test_user_cannot_send_message_to_another_users_chat(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)

    await login_user_b(client, email_backend)
    response = await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "Hello"})

    assert response.status_code == 404


async def test_user_cannot_list_another_users_messages(
    client: AsyncClient, email_backend: RecordingEmailBackend, install_fake_model: InstallFakeModel
) -> None:
    await login_user_a(client, email_backend)
    chat = await create_chat(client)
    install_fake_model(FakeChatModel(turns=[FakeTurn(text_chunks=["hi"])]))
    await client.post(f"/api/v1/chats/{chat['id']}/messages", json={"message": "Hello"})

    await login_user_b(client, email_backend)
    response = await client.get(f"/api/v1/chats/{chat['id']}/messages")

    assert response.status_code == 404
