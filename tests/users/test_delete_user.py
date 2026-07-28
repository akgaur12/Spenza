"""Integration tests for DELETE /api/users/delete-user."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "delete.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "delete_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


async def test_delete_user_with_correct_password_succeeds(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.request(
        "DELETE",
        "/api/users/delete-user",
        json={"current_password": CREDENTIALS["password"]},
    )
    assert response.status_code == 200

    login_after_delete = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    assert login_after_delete.status_code == 401
    assert login_after_delete.json()["error_code"] == "INVALID_CREDENTIALS"


async def test_delete_user_with_wrong_password_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.request(
        "DELETE",
        "/api/users/delete-user",
        json={"current_password": "WrongPassword1!"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"

    login_still_works = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    assert login_still_works.status_code == 200


async def test_delete_user_requires_authentication(client: AsyncClient) -> None:
    response = await client.request(
        "DELETE",
        "/api/users/delete-user",
        json={"current_password": "whatever"},
    )
    assert response.status_code == 401
