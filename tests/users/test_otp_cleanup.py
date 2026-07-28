"""Unit tests for `cleanup_expired_otps` (the email_otps housekeeping sweep)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.app_config import settings
from src.modules.users.models import EmailOTP, OTPPurpose, User
from src.modules.users.repository import UserRepository
from src.modules.users.service import cleanup_expired_otps


async def _make_user_with_otp(
    session: AsyncSession, *, email: str, created_at: datetime
) -> EmailOTP:
    user = User(email=email, username=email.split("@")[0], password_hash="x")
    session.add(user)
    await session.flush()

    otp = EmailOTP(
        user_id=user.id,
        otp_hash="x",
        purpose=OTPPurpose.SIGNUP,
        expires_at=created_at + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        created_at=created_at,
    )
    session.add(otp)
    await session.flush()
    return otp


async def test_cleanup_deletes_only_rows_past_the_retention_window(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    retention = timedelta(minutes=settings.OTP_EXPIRE_MINUTES * 2)

    async with db_session_factory() as session:
        stale = await _make_user_with_otp(
            session, email="stale@example.com", created_at=now - retention - timedelta(minutes=1)
        )
        fresh = await _make_user_with_otp(
            session, email="fresh@example.com", created_at=now - timedelta(minutes=1)
        )
        await session.commit()
        stale_id, fresh_id = stale.id, fresh.id

    async with db_session_factory() as session:
        deleted = await cleanup_expired_otps(session)

    assert deleted == 1

    async with db_session_factory() as session:
        remaining_ids = set((await session.execute(select(EmailOTP.id))).scalars().all())
        assert stale_id not in remaining_ids
        assert fresh_id in remaining_ids


async def test_cleanup_is_a_no_op_when_nothing_is_stale(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        users = UserRepository(session)
        user = users.create(email="active@example.com", username="active", password_hash="x")
        await session.flush()
        session.add(
            EmailOTP(
                user_id=user.id,
                otp_hash="x",
                purpose=OTPPurpose.SIGNUP,
                expires_at=datetime.now(UTC) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        deleted = await cleanup_expired_otps(session)

    assert deleted == 0
