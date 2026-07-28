"""Integration tests for POST /api/users/login, /login-json, and GET /me."""

from httpx import AsyncClient

from src.core.app_config import settings
from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "login.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "login_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


async def test_login_success_sets_cookies_and_returns_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)

    response = await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["data"]["email"] == CREDENTIALS["email"]
    assert settings.ACCESS_TOKEN_COOKIE_NAME in response.cookies
    assert settings.REFRESH_TOKEN_COOKIE_NAME in response.cookies


async def test_login_with_username_succeeds(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)

    response = await client.post(
        "/api/users/login",
        json={"identifier": SIGNUP_PAYLOAD["username"], "password": CREDENTIALS["password"]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["email"] == CREDENTIALS["email"]


async def test_login_json_returns_token_pair_in_body(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)

    response = await client.post("/api/users/login-json", json=LOGIN_PAYLOAD)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"


async def test_login_wrong_password_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)

    response = await client.post(
        "/api/users/login",
        json={"identifier": CREDENTIALS["email"], "password": "WrongPassword1!"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_identifier_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/login",
        json={"identifier": "nobody@example.com", "password": "SecureP@ss1"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"


async def test_login_unverified_account_rejected(client: AsyncClient) -> None:
    payload = {
        "email": "unverified@example.com",
        "username": "unverified_user",
        "password": "SecureP@ss1",
    }
    await client.post("/api/users/signup", json=payload)

    response = await client.post(
        "/api/users/login",
        json={"identifier": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "EMAIL_NOT_VERIFIED"


async def test_login_locks_account_after_max_failed_attempts(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    payload = {
        "email": "lockout@example.com",
        "username": "lockout_user",
        "password": "SecureP@ss1",
    }
    await register_verified_user(client, email_backend, payload)

    for _ in range(settings.LOGIN_MAX_FAILED_ATTEMPTS):
        response = await client.post(
            "/api/users/login",
            json={"identifier": payload["email"], "password": "WrongPassword1!"},
        )
        assert response.status_code == 401

    locked_response = await client.post(
        "/api/users/login",
        json={"identifier": payload["email"], "password": payload["password"]},
    )
    assert locked_response.status_code == 429
    assert locked_response.json()["error_code"] == "ACCOUNT_LOCKED"


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/users/me")
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_ACCESS_TOKEN"


async def test_me_returns_current_user_after_login(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/login", json=LOGIN_PAYLOAD)

    response = await client.get("/api/users/me")

    assert response.status_code == 200
    assert response.json()["data"]["email"] == CREDENTIALS["email"]
