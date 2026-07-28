"""Integration tests for the full forgot -> verify -> reset password flow."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

CREDENTIALS = {"email": "reset.user@example.com", "password": "SecureP@ss1"}
SIGNUP_PAYLOAD = {**CREDENTIALS, "username": "reset_user"}
LOGIN_PAYLOAD = {"identifier": CREDENTIALS["email"], "password": CREDENTIALS["password"]}
NEW_PASSWORD = "NewSecureP@ss1"


async def _get_reset_token(client: AsyncClient, email_backend: RecordingEmailBackend) -> str:
    email_backend.sent.clear()
    await client.post("/api/users/forgot-password", json={"email": CREDENTIALS["email"]})
    otp = email_backend.latest_otp(CREDENTIALS["email"])

    verify_resp = await client.post(
        "/api/users/verify-reset-otp", json={"email": CREDENTIALS["email"], "otp": otp}
    )
    assert verify_resp.status_code == 200
    return verify_resp.json()["data"]["reset_token"]


async def test_full_reset_password_flow_invalidates_sessions_and_old_password(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    login_resp = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    assert login_resp.status_code == 200

    reset_token = await _get_reset_token(client, email_backend)

    reset_resp = await client.post(
        "/api/users/reset-password",
        json={"reset_token": reset_token, "new_password": NEW_PASSWORD},
    )
    assert reset_resp.status_code == 200

    refresh_resp = await client.post("/api/users/refresh-token")
    assert refresh_resp.status_code == 401

    old_login = await client.post("/api/users/login", json=LOGIN_PAYLOAD)
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/users/login", json={"identifier": CREDENTIALS["email"], "password": NEW_PASSWORD}
    )
    assert new_login.status_code == 200


async def test_verify_reset_otp_wrong_code_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    await client.post("/api/users/forgot-password", json={"email": CREDENTIALS["email"]})

    response = await client.post(
        "/api/users/verify-reset-otp", json={"email": CREDENTIALS["email"], "otp": "000000"}
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_OTP"


async def test_reset_password_rejects_reused_reset_token(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    reset_token = await _get_reset_token(client, email_backend)

    first = await client.post(
        "/api/users/reset-password",
        json={"reset_token": reset_token, "new_password": NEW_PASSWORD},
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/users/reset-password",
        json={"reset_token": reset_token, "new_password": "AnotherP@ss2"},
    )
    assert second.status_code == 400
    assert second.json()["error_code"] == "INVALID_RESET_TOKEN"


async def test_reset_password_rejects_malformed_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/reset-password",
        json={"reset_token": "not-a-real-token", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_RESET_TOKEN"
