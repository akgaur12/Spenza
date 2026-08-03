"""Integration tests for POST /api/users/resend-otp."""

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.app_config import settings
from src.modules.users.models import EmailOTP
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend, register_verified_user

SIGNUP_PAYLOAD = {
    "email": "resend.user@example.com",
    "username": "resend_user",
    "password": "SecureP@ss1",
}


async def test_resend_otp_sends_new_code_for_unverified_user(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)
    original = settings.OTP_RESEND_COOLDOWN_SECONDS
    try:
        settings.OTP_RESEND_COOLDOWN_SECONDS = -1

        response = await client.post(
            "/api/users/resend-otp", json={"email": SIGNUP_PAYLOAD["email"]}
        )
        assert response.status_code == 200

        otp = email_backend.latest_otp(SIGNUP_PAYLOAD["email"])
        verify_resp = await client.post(
            "/api/users/verify-signup-otp",
            json={"email": SIGNUP_PAYLOAD["email"], "otp": otp},
        )
        assert verify_resp.status_code == 200
    finally:
        settings.OTP_RESEND_COOLDOWN_SECONDS = original


async def test_resend_otp_replaces_previous_otp_row(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)
    original = settings.OTP_RESEND_COOLDOWN_SECONDS
    try:
        settings.OTP_RESEND_COOLDOWN_SECONDS = -1
        await client.post("/api/users/resend-otp", json={"email": SIGNUP_PAYLOAD["email"]})
    finally:
        settings.OTP_RESEND_COOLDOWN_SECONDS = original

    async with db_session_factory() as session:
        user = await UserRepository(session).get_by_email(SIGNUP_PAYLOAD["email"])
        assert user is not None
        remaining = await session.execute(select(EmailOTP).where(EmailOTP.user_id == user.id))
        assert len(remaining.scalars().all()) == 1


async def test_resend_otp_within_cooldown_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await client.post("/api/users/signup", json=SIGNUP_PAYLOAD)

    response = await client.post(
        "/api/users/resend-otp", json={"email": SIGNUP_PAYLOAD["email"]}
    )

    assert response.status_code == 429
    assert response.json()["error_code"] == "OTP_RESEND_COOLDOWN"


async def test_resend_otp_unknown_email_does_not_leak_existence(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    response = await client.post("/api/users/resend-otp", json={"email": "nobody@example.com"})

    assert response.status_code == 200
    assert len(email_backend.sent) == 0


async def test_resend_otp_already_verified_user_does_not_send(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await register_verified_user(client, email_backend, SIGNUP_PAYLOAD)
    email_backend.sent.clear()

    response = await client.post(
        "/api/users/resend-otp", json={"email": SIGNUP_PAYLOAD["email"]}
    )

    assert response.status_code == 200
    assert len(email_backend.sent) == 0
