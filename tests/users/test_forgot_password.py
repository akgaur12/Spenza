"""Integration tests for POST /api/users/forgot-password."""

from httpx import AsyncClient

from tests.conftest import RecordingEmailBackend, register_verified_user

SIGNUP_PAYLOAD = {
    "email": "forgot.user@example.com",
    "username": "forgot_user",
    "password": "SecureP@ss1",
}


async def test_forgot_password_sends_otp_for_existing_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    email_backend.sent.clear()

    response = await client.post(
        "/api/users/forgot-password", json={"email": SIGNUP_PAYLOAD["email"]}
    )

    assert response.status_code == 200
    assert len(email_backend.sent) == 1
    assert email_backend.sent[0]["subject"] == "Reset your Spenza password"


async def test_forgot_password_unknown_email_is_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    response = await client.post("/api/users/forgot-password", json={"email": "nobody@example.com"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "USER_NOT_FOUND"
    assert len(email_backend.sent) == 0
