"""Shared pytest fixtures: isolated in-memory DB per test, a fake email
backend that records what would have been sent, and an httpx AsyncClient
wired to the FastAPI app with dependencies overridden accordingly.
"""

import re
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.app import app as fastapi_app
from src.core.app_config import settings
from src.core.database import Base, get_db_session
from src.core.exceptions import AppError
from src.core.rate_limit import limiter
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.users.dependencies import get_user_service
from src.modules.users.models import UserRole
from src.modules.users.repository import UserRepository
from src.modules.users.service import UserService
from src.shared.email.backend import EmailBackend
from src.shared.email.service import EmailService


@pytest.fixture(autouse=True)
def _disable_rate_limiting() -> None:
    """Rate limits are backed by process-global in-memory state, which would
    otherwise leak between tests. Not the behavior under test here.
    """
    limiter.enabled = False


@pytest.fixture(autouse=True)
def _force_console_email_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """`EmailDeliveryService` and `EmailService` both read
    `settings.EMAIL_BACKEND` fresh on every construction, so whatever a
    developer's local `.env` has set (e.g. `EMAIL_BACKEND=resend` while
    testing that integration by hand, with a real API key) would otherwise
    leak into the suite and make real network calls to a live provider.
    Forcing it here keeps every send on the network-free console backend
    regardless of `.env`. Individual tests that need to exercise the
    smtp/resend selection logic itself (see `test_provider.py`,
    `test_backend.py`) still override it with their own `monkeypatch`, which
    layers on top of this and unwinds first.
    """
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "console")


OTP_PATTERN = re.compile(r"<!-- OTP:(\d+) -->")


def extract_otp(html_body: str) -> str:
    """Pull the OTP out of a rendered email body via its HTML comment marker."""
    match = OTP_PATTERN.search(html_body)
    assert match, f"No OTP marker found in email body: {html_body!r}"
    return match.group(1)


class RecordingEmailBackend(EmailBackend):
    """Captures every "sent" email in memory instead of delivering it."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "html_body": html_body})

    def latest_otp(self, to: str) -> str:
        matching = [email for email in self.sent if email["to"] == to]
        assert matching, f"No email sent to {to}"
        return extract_otp(matching[-1]["html_body"])


@pytest_asyncio.fixture
async def db_session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    await engine.dispose()


@pytest.fixture
def email_backend() -> RecordingEmailBackend:
    return RecordingEmailBackend()


@pytest_asyncio.fixture
async def client(
    db_session_factory: async_sessionmaker[AsyncSession],
    email_backend: RecordingEmailBackend,
) -> AsyncGenerator[AsyncClient]:
    async def override_get_db_session() -> AsyncGenerator[AsyncSession]:
        async with db_session_factory() as session:
            try:
                yield session
            except AppError:
                await session.commit()
                raise
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    async def override_get_user_service(
        session: AsyncSession = Depends(override_get_db_session),
        email_delivery_service: EmailDeliveryService = Depends(get_email_delivery_service),
    ) -> UserService:
        return UserService(session, EmailService(backend=email_backend), email_delivery_service)

    fastapi_app.dependency_overrides[get_db_session] = override_get_db_session
    fastapi_app.dependency_overrides[get_user_service] = override_get_user_service

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://localhost") as ac:
        yield ac

    fastapi_app.dependency_overrides.clear()


DEFAULT_SIGNUP_PAYLOAD = {
    "email": "jane.doe@example.com",
    "username": "jane_doe",
    "password": "SecureP@ss1",
}


async def register_verified_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    payload: dict[str, str] | None = None,
) -> dict[str, str]:
    """Sign up a user and verify their email via the OTP captured by the fake
    email backend, returning the signup payload used.
    """
    body = payload or DEFAULT_SIGNUP_PAYLOAD
    signup_resp = await client.post("/api/users/signup", json=body)
    assert signup_resp.status_code == 201, signup_resp.text

    otp = email_backend.latest_otp(body["email"])
    verify_resp = await client.post(
        "/api/users/verify-signup-otp", json={"email": body["email"], "otp": otp}
    )
    assert verify_resp.status_code == 200, verify_resp.text
    return body


async def promote_to_admin(
    db_session_factory: async_sessionmaker[AsyncSession], email: str
) -> None:
    """Flip an existing user's role to admin directly via the DB, bypassing
    the API (there is no signup-time way to become an admin).
    """
    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email(email)
        assert user is not None, f"No user found with email {email}"
        user.role = UserRole.ADMIN
        await session.commit()
