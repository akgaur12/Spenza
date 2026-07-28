"""Integration tests for POST /api/users/change-password."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "changepw.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "changepw_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}
NEW_PASSWORD = "AnotherSecureP@ss2"


async def test_change_password_success_revokes_sessions(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.post(
        "/api/users/change-password",
        json={"current_password": CREDENTIALS["password"], "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 200

    refresh_resp = await client.post("/api/users/refresh-token")
    assert refresh_resp.status_code == 401

    new_login = await client.post(
        "/api/users/login", json={"identifier": CREDENTIALS["email"], "password": NEW_PASSWORD}
    )
    assert new_login.status_code == 200


async def test_change_password_wrong_current_password_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.post(
        "/api/users/change-password",
        json={"current_password": "WrongPassword1!", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"


async def test_change_password_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/change-password",
        json={"current_password": "whatever", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401
