"""Data-access layer for the `users` module.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns. `UserService` composes these to implement behavior.
"""

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.users.models import EmailOTP, OTPPurpose, RefreshSession, User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_many_by_id(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
        """Batch-fetch owners by id, keyed by id — used by cross-user batch
        jobs (e.g. the recurring-expenses scheduler) to avoid one query per
        row when processing many users' records in a single pass.
        """
        if not user_ids:
            return {}
        result = await self._session.execute(select(User).where(User.id.in_(user_ids)))
        return {user.id: user for user in result.scalars().all()}

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    def create(
        self, *, email: str, username: str, password_hash: str, full_name: str | None = None
    ) -> User:
        user = User(
            email=email.lower(),
            username=username,
            password_hash=password_hash,
            full_name=full_name,
        )
        self._session.add(user)
        return user

    async def flush(self) -> None:
        await self._session.flush()

    async def delete(self, user: User) -> None:
        await self._session.delete(user)

    async def list_all(self, *, offset: int, limit: int) -> list[User]:
        result = await self._session.execute(
            select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(User))
        return result.scalar_one()

    async def count_by_role(self, role: UserRole) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(User).where(User.role == role)
        )
        return result.scalar_one()

    async def delete_unverified_older_than(self, cutoff: datetime) -> int:
        """Bulk-delete accounts that never completed signup verification —
        used by `core.cleanup` to enforce `USER_UNVERIFIED_RETENTION_DAYS`.
        A verified account is never touched regardless of age. Relies on
        the `ON DELETE CASCADE` foreign keys from `email_otps`,
        `refresh_sessions`, etc. (real DB-level constraints, not just the
        ORM-side `cascade="all, delete-orphan"`, which only fires on a
        session-tracked `session.delete()`, not a bulk statement like this).
        """
        result = await self._session.execute(
            delete(User).where(User.is_verified.is_(False), User.created_at < cutoff)
        )
        return cast(CursorResult[Any], result).rowcount or 0


class RefreshSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: uuid.UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        device: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> RefreshSession:
        session_row = RefreshSession(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            device=device,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(session_row)
        return session_row

    async def get_by_id(self, session_id: uuid.UUID) -> RefreshSession | None:
        return await self._session.get(RefreshSession, session_id)

    async def get_by_token_hash(self, token_hash: str) -> RefreshSession | None:
        result = await self._session.execute(
            select(RefreshSession).where(RefreshSession.refresh_token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_active_for_user(self, user_id: uuid.UUID) -> list[RefreshSession]:
        result = await self._session.execute(
            select(RefreshSession)
            .where(RefreshSession.user_id == user_id, RefreshSession.revoked.is_(False))
            .order_by(RefreshSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke(self, session_row: RefreshSession) -> None:
        session_row.revoked = True

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self._session.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == user_id, RefreshSession.revoked.is_(False))
            .values(revoked=True)
        )

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Bulk-delete sessions that have been dead (revoked, or past
        `expires_at`) since before `cutoff` — used by `core.cleanup` to
        enforce `REFRESH_SESSION_RETENTION_DAYS`. A still-valid session is
        never touched regardless of age. `updated_at` is what moves when a
        session is revoked (`revoke`/`revoke_all_for_user` above), so it
        marks how long ago a revoked session actually died.
        """
        result = await self._session.execute(
            delete(RefreshSession).where(
                or_(
                    RefreshSession.expires_at < cutoff,
                    (RefreshSession.revoked.is_(True)) & (RefreshSession.updated_at < cutoff),
                )
            )
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def flush(self) -> None:
        await self._session.flush()


class EmailOTPRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: uuid.UUID,
        otp_hash: str,
        purpose: OTPPurpose,
        expires_at: datetime,
    ) -> EmailOTP:
        otp = EmailOTP(user_id=user_id, otp_hash=otp_hash, purpose=purpose, expires_at=expires_at)
        self._session.add(otp)
        return otp

    async def get_by_id(self, otp_id: uuid.UUID) -> EmailOTP | None:
        return await self._session.get(EmailOTP, otp_id)

    async def get_latest_pending(self, user_id: uuid.UUID, purpose: OTPPurpose) -> EmailOTP | None:
        result = await self._session.execute(
            select(EmailOTP)
            .where(
                EmailOTP.user_id == user_id,
                EmailOTP.purpose == purpose,
                EmailOTP.verified.is_(False),
            )
            .order_by(EmailOTP.created_at.desc())
        )
        return result.scalars().first()

    async def delete(self, otp: EmailOTP) -> None:
        await self._session.delete(otp)

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = await self._session.execute(delete(EmailOTP).where(EmailOTP.created_at < cutoff))
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def flush(self) -> None:
        await self._session.flush()
