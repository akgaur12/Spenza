"""Integration tests for PATCH /api/users/update-username."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "rename.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "rename_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


async def test_update_username_success(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.patch(
        "/api/users/update-username", json={"new_username": "renamed_user"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["username"] == "renamed_user"

    me_resp = await client.get("/api/users/me")
    assert me_resp.json()["data"]["username"] == "renamed_user"


async def test_update_username_conflict_with_existing_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    other_payload = {
        "email": "other.user@example.com",
        "username": "taken_username",
        "password": "SecureP@ss1",
    }
    await register_verified_user(client, email_backend, other_payload)

    await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    response = await client.patch(
        "/api/users/update-username", json={"new_username": "taken_username"}
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "USERNAME_ALREADY_EXISTS"


async def test_update_username_requires_authentication(client: AsyncClient) -> None:
    response = await client.patch(
        "/api/users/update-username", json={"new_username": "someone_new"}
    )
    assert response.status_code == 401


async def test_update_username_rejects_invalid_format(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.patch("/api/users/update-username", json={"new_username": "1bad"})
    assert response.status_code == 422
