"""Integration tests for POST /api/users/refresh-token (rotation + revocation)."""

from httpx import AsyncClient

from src.core.app_config import settings
from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "refresh.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "refresh_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}


async def test_refresh_token_rotates_and_issues_new_access_token(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    login_resp = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    old_refresh_token = login_resp.cookies[settings.REFRESH_TOKEN_COOKIE_NAME]
    old_access_token = login_resp.cookies[settings.ACCESS_TOKEN_COOKIE_NAME]

    refresh_resp = await client.post("/api/users/refresh-token")

    assert refresh_resp.status_code == 200
    new_refresh_token = refresh_resp.cookies[settings.REFRESH_TOKEN_COOKIE_NAME]
    new_access_token = refresh_resp.cookies[settings.ACCESS_TOKEN_COOKIE_NAME]
    assert new_refresh_token != old_refresh_token
    assert new_access_token != old_access_token


async def test_refresh_token_missing_cookie_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/users/refresh-token")
    assert response.status_code == 401
    assert response.json()["error_code"] == "INVALID_REFRESH_TOKEN"


async def test_reusing_rotated_refresh_token_is_revoked(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    login_resp = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    old_refresh_token = login_resp.cookies[settings.REFRESH_TOKEN_COOKIE_NAME]

    await client.post("/api/users/refresh-token")

    client.cookies.set(settings.REFRESH_TOKEN_COOKIE_NAME, old_refresh_token)
    reuse_resp = await client.post("/api/users/refresh-token")

    assert reuse_resp.status_code == 401
    assert reuse_resp.json()["error_code"] == "REFRESH_TOKEN_REVOKED"
