"""Integration tests for POST /api/users/verify-signup-otp."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.app_config import settings
from src.modules.users.models import EmailOTP
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend

SIGNUP_PAYLOAD = {
    "email": "otp.user@example.com",
    "username": "otp_user",
    "password": "SecureP@ss1",
}


async def test_verify_signup_otp_success_activates_account_and_sends_welcome(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)
    otp = email_backend.latest_otp(SIGNUP_PAYLOAD["email"])

    response = await client.post(
        "/api/users/verify-signup-otp", json={"email": SIGNUP_PAYLOAD["email"], "otp": otp}
    )

    assert response.status_code == 200
    assert response.json()["data"]["is_verified"] is True
    assert any(e["subject"] == "Welcome to Spenza" for e in email_backend.sent)


async def test_verify_signup_otp_success_deletes_otp_row(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)
    otp = email_backend.latest_otp(SIGNUP_PAYLOAD["email"])

    response = await client.post(
        "/api/users/verify-signup-otp", json={"email": SIGNUP_PAYLOAD["email"], "otp": otp}
    )
    assert response.status_code == 200

    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(SIGNUP_PAYLOAD["email"])
        assert user is not None
        remaining = await session.execute(select(EmailOTP).where(EmailOTP.user_id == user.id))
        assert remaining.scalars().all() == []


async def test_verify_signup_otp_wrong_code_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)

    response = await client.post(
        "/api/users/verify-signup-otp", json={"email": SIGNUP_PAYLOAD["email"], "otp": "000000"}
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_OTP"


async def test_verify_signup_otp_unknown_email_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/users/verify-signup-otp",
        json={"email": "nobody@example.com", "otp": "123456"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "USER_NOT_FOUND"


async def test_verify_signup_otp_exceeding_attempts_locks_out(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)

    for _ in range(settings.OTP_MAX_ATTEMPTS):
        response = await client.post(
            "/api/users/verify-signup-otp",
            json={"email": SIGNUP_PAYLOAD["email"], "otp": "000000"},
        )
        assert response.status_code == 400

    final_response = await client.post(
        "/api/users/verify-signup-otp",
        json={"email": SIGNUP_PAYLOAD["email"], "otp": "000000"},
    )
    assert final_response.status_code == 429
    assert final_response.json()["error_code"] == "OTP_ATTEMPTS_EXCEEDED"


async def test_verify_signup_otp_expired_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    original = settings.OTP_EXPIRE_MINUTES
    try:
        settings.OTP_EXPIRE_MINUTES = -1
        await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)
        otp = email_backend.latest_otp(SIGNUP_PAYLOAD["email"])
    finally:
        settings.OTP_EXPIRE_MINUTES = original

    response = await client.post(
        "/api/users/verify-signup-otp", json={"email": SIGNUP_PAYLOAD["email"], "otp": otp}
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "OTP_EXPIRED"
