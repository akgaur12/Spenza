"""Business logic for the `users` module (signup, auth, password, profile).

Depends only on repositories + shared infra (security, email, logging) —
never on FastAPI request/response objects — so it stays fully unit-testable.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.logger import get_logger
from src.core.security import (
    DecodedToken,
    TokenExpiredError,
    TokenInvalidError,
    TokenType,
    create_access_token,
    create_action_token,
    decode_action_token,
    decode_token,
    generate_otp,
    generate_refresh_token,
    hash_otp,
    hash_password,
    hash_refresh_token,
    verify_otp,
    verify_password,
    verify_refresh_token,
)
from src.modules.import_export.export_service import ExportService
from src.modules.notifications.delivery.provider import EmailAttachment
from src.modules.notifications.delivery.templates import render_template
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.users.exceptions import (
    AccountDataExportFailedError,
    AccountInactiveError,
    AccountLockedError,
    CannotDemoteLastAdminError,
    CannotModifyOwnAccountError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidOTPError,
    InvalidRefreshTokenError,
    InvalidResetTokenError,
    OTPAttemptsExceededError,
    OTPExpiredError,
    OTPResendCooldownError,
    RefreshTokenExpiredError,
    RefreshTokenRevokedError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from src.modules.users.models import EmailOTP, OTPPurpose, RefreshSession, User, UserRole
from src.modules.users.repository import (
    EmailOTPRepository,
    RefreshSessionRepository,
    UserRepository,
)
from src.modules.users.schemas import (
    ChangePasswordRequest,
    ResetPasswordRequest,
    SignupRequest,
    UpdateProfileRequest,
    VerifyResetOTPRequest,
    VerifySignupOTPRequest,
)
from src.shared.email.service import EmailService, get_email_service

logger = get_logger(__name__)

RESET_PASSWORD_PURPOSE = "password_reset"  # noqa: S105


@dataclass(frozen=True, slots=True)
class DeviceContext:
    """Client metadata captured at login/refresh time for session tracking."""

    device: str | None
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class TokenIssue:
    access_token: str
    refresh_token: str
    session_id: uuid.UUID


class UserService:
    def __init__(
        self,
        session: AsyncSession,
        email_service: EmailService | None = None,
        email_delivery_service: EmailDeliveryService | None = None,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_sessions = RefreshSessionRepository(session)
        self._export = ExportService(session)
        self._email_delivery = email_delivery_service or EmailDeliveryService(session)
        self._otps = EmailOTPRepository(session)
        self._email = email_service or get_email_service()

    # ── Signup / email verification ─────────────────────────────────────

    async def signup(self, data: SignupRequest) -> User:
        existing_by_email = await self._users.get_by_email(data.email)
        if existing_by_email and existing_by_email.is_verified:
            raise EmailAlreadyExistsError()

        existing_by_username = await self._users.get_by_username(data.username)
        if existing_by_username and existing_by_username.id != (
            existing_by_email.id if existing_by_email else None
        ):
            raise UsernameAlreadyExistsError()

        password_hash = hash_password(data.password)

        if existing_by_email:
            user = existing_by_email
            user.username = data.username
            user.password_hash = password_hash
            user.full_name = data.full_name
        else:
            user = self._users.create(
                email=data.email,
                username=data.username,
                password_hash=password_hash,
                full_name=data.full_name,
            )
        await self._users.flush()

        await self._issue_otp(user, purpose=OTPPurpose.SIGNUP)
        logger.info("user.signup.initiated", user_id=str(user.id))
        return user

    async def _issue_otp(self, user: User, *, purpose: OTPPurpose) -> str:
        raw_otp = generate_otp()
        self._otps.create(
            user_id=user.id,
            otp_hash=hash_otp(raw_otp),
            purpose=purpose,
            expires_at=datetime.now(UTC) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        )
        await self._otps.flush()

        if purpose is OTPPurpose.SIGNUP:
            await self._email.send_signup_otp(to=user.email, username=user.username, otp=raw_otp)
        else:
            await self._email.send_password_reset_otp(
                to=user.email, username=user.username, otp=raw_otp
            )
        return raw_otp

    async def _consume_otp(self, user: User, *, purpose: OTPPurpose, raw_otp: str) -> EmailOTP:
        otp = await self._otps.get_latest_pending(user.id, purpose)
        if otp is None:
            raise InvalidOTPError()

        if otp.expires_at < datetime.now(UTC):
            raise OTPExpiredError()

        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise OTPAttemptsExceededError()

        if not verify_otp(raw_otp, otp.otp_hash):
            otp.attempts += 1
            await self._otps.flush()
            raise InvalidOTPError()

        return otp

    async def verify_signup_otp(self, data: VerifySignupOTPRequest) -> User:
        user = await self._users.get_by_email(data.email)
        if user is None:
            raise UserNotFoundError()
        if user.is_verified:
            return user

        otp = await self._consume_otp(user, purpose=OTPPurpose.SIGNUP, raw_otp=data.otp)
        await self._otps.delete(otp)
        user.is_verified = True
        await self._users.flush()

        await self._email.send_welcome_email(to=user.email, username=user.username)
        logger.info("user.signup.verified", user_id=str(user.id))
        return user

    async def resend_otp(self, email: str, *, purpose: OTPPurpose) -> None:
        user = await self._users.get_by_email(email)
        if user is None:
            logger.info("user.resend_otp.unknown_email")
            return
        if purpose is OTPPurpose.SIGNUP and user.is_verified:
            return

        latest = await self._otps.get_latest_pending(user.id, purpose)
        if latest is not None:
            cooldown_until = latest.created_at + timedelta(
                seconds=settings.OTP_RESEND_COOLDOWN_SECONDS
            )
            if datetime.now(UTC) < cooldown_until:
                raise OTPResendCooldownError()
            await self._otps.delete(latest)

        await self._issue_otp(user, purpose=purpose)
        logger.info("user.resend_otp.sent", user_id=str(user.id))

    # ── Login / tokens ───────────────────────────────────────────────────

    async def _check_login_eligibility(self, user: User) -> None:
        if user.locked_until and user.locked_until > datetime.now(UTC):
            raise AccountLockedError(
                message=f"Account locked until {user.locked_until.isoformat()}"
            )
        if not user.is_active:
            raise AccountInactiveError()
        if not user.is_verified:
            raise EmailNotVerifiedError()

    async def _register_failed_login(self, user: User) -> None:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            lockout = timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
            user.locked_until = datetime.now(UTC) + lockout
        await self._users.flush()

    async def authenticate(self, *, identifier: str, password: str) -> User:
        user = await self._users.get_by_email(identifier) or await self._users.get_by_username(
            identifier
        )
        if user is None:
            raise InvalidCredentialsError()

        if user.locked_until and user.locked_until > datetime.now(UTC):
            raise AccountLockedError(
                message=f"Account locked until {user.locked_until.isoformat()}"
            )

        if not verify_password(password, user.password_hash):
            await self._register_failed_login(user)
            logger.warning("user.login.failed", user_id=str(user.id))
            raise InvalidCredentialsError()

        await self._check_login_eligibility(user)

        user.failed_login_attempts = 0
        user.locked_until = None
        await self._users.flush()
        logger.info("user.login.success", user_id=str(user.id))
        return user

    async def issue_token_pair(self, user: User, device_ctx: DeviceContext) -> TokenIssue:
        raw_refresh = generate_refresh_token()
        session_row = self._refresh_sessions.create(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(raw_refresh),
            expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            device=device_ctx.device,
            ip_address=device_ctx.ip_address,
            user_agent=device_ctx.user_agent,
        )
        await self._refresh_sessions.flush()

        access_token = create_access_token(user.id, session_row.id)
        return TokenIssue(
            access_token=access_token, refresh_token=raw_refresh, session_id=session_row.id
        )

    async def _get_valid_session(self, raw_refresh_token: str) -> RefreshSession:
        session_row = await self._refresh_sessions.get_by_token_hash(
            hash_refresh_token(raw_refresh_token)
        )
        if session_row is None or not verify_refresh_token(
            raw_refresh_token, session_row.refresh_token_hash
        ):
            raise InvalidRefreshTokenError()
        if session_row.revoked:
            raise RefreshTokenRevokedError()
        if session_row.expires_at < datetime.now(UTC):
            raise RefreshTokenExpiredError()
        return session_row

    async def refresh_tokens(
        self, raw_refresh_token: str, device_ctx: DeviceContext
    ) -> tuple[User, TokenIssue]:
        session_row = await self._get_valid_session(raw_refresh_token)
        user = await self._users.get_by_id(session_row.user_id)
        if user is None or not user.is_active:
            raise InvalidRefreshTokenError()

        await self._refresh_sessions.revoke(session_row)
        session_row.last_used_at = datetime.now(UTC)
        await self._refresh_sessions.flush()

        issued = await self.issue_token_pair(user, device_ctx)
        logger.info("user.token.refreshed", user_id=str(user.id))
        return user, issued

    async def logout(self, raw_refresh_token: str) -> None:
        session_row = await self._refresh_sessions.get_by_token_hash(
            hash_refresh_token(raw_refresh_token)
        )
        if session_row is not None and not session_row.revoked:
            await self._refresh_sessions.revoke(session_row)
            await self._refresh_sessions.flush()
            logger.info("user.logout", user_id=str(session_row.user_id))

    async def logout_all_devices(self, user_id: uuid.UUID) -> None:
        await self._refresh_sessions.revoke_all_for_user(user_id)
        logger.info("user.logout_all", user_id=str(user_id))

    async def get_user_from_access_token(self, access_token: str) -> User:
        try:
            decoded: DecodedToken = decode_token(access_token, expected_type=TokenType.ACCESS)
        except (TokenExpiredError, TokenInvalidError) as exc:
            raise InvalidAccessTokenError(message=str(exc)) from exc

        if decoded.session_id is None:
            raise InvalidAccessTokenError()

        session_row = await self._refresh_sessions.get_by_id(uuid.UUID(decoded.session_id))
        if session_row is None or session_row.revoked:
            raise InvalidAccessTokenError(message="Session has been revoked")

        user = await self._users.get_by_id(uuid.UUID(decoded.subject))
        if user is None or not user.is_active:
            raise InvalidAccessTokenError()
        return user

    # ── Password management ──────────────────────────────────────────────

    async def forgot_password(self, email: str) -> None:
        user = await self._users.get_by_email(email)
        if user is None:
            raise UserNotFoundError()
        if not user.is_active:
            logger.info("user.forgot_password.inactive_account", user_id=str(user.id))
            return
        await self._issue_otp(user, purpose=OTPPurpose.PASSWORD_RESET)
        logger.info("user.forgot_password.otp_sent", user_id=str(user.id))

    async def verify_reset_otp(self, data: VerifyResetOTPRequest) -> tuple[str, int]:
        user = await self._users.get_by_email(data.email)
        if user is None:
            raise UserNotFoundError()

        otp = await self._consume_otp(user, purpose=OTPPurpose.PASSWORD_RESET, raw_otp=data.otp)
        otp.verified = True
        await self._otps.flush()

        reset_token = create_action_token(
            subject=str(user.id),
            purpose=RESET_PASSWORD_PURPOSE,
            expire_minutes=settings.OTP_EXPIRE_MINUTES,
            extra_claims={"otp_id": str(otp.id)},
        )
        logger.info("user.reset_otp.verified", user_id=str(user.id))
        return reset_token, settings.OTP_EXPIRE_MINUTES

    async def reset_password(self, data: ResetPasswordRequest) -> User:
        try:
            payload = decode_action_token(data.reset_token, expected_purpose=RESET_PASSWORD_PURPOSE)
        except (TokenExpiredError, TokenInvalidError) as exc:
            raise InvalidResetTokenError(message=str(exc)) from exc

        otp = await self._otps.get_by_id(uuid.UUID(payload["otp_id"]))
        if otp is None or not otp.verified:
            raise InvalidResetTokenError()

        user = await self._users.get_by_id(uuid.UUID(payload["sub"]))
        if user is None:
            raise InvalidResetTokenError()

        user.password_hash = hash_password(data.new_password)
        user.failed_login_attempts = 0
        user.locked_until = None
        await self._otps.delete(otp)
        await self._refresh_sessions.revoke_all_for_user(user.id)
        await self._users.flush()
        logger.info("user.password.reset", user_id=str(user.id))
        return user

    async def change_password(self, user: User, data: ChangePasswordRequest) -> None:
        if not verify_password(data.current_password, user.password_hash):
            raise InvalidCredentialsError(message="Current password is incorrect")

        user.password_hash = hash_password(data.new_password)
        await self._refresh_sessions.revoke_all_for_user(user.id)
        await self._users.flush()
        logger.info("user.password.changed", user_id=str(user.id))

    # ── Profile management ────────────────────────────────────────────────

    async def update_username(self, user: User, new_username: str) -> User:
        existing = await self._users.get_by_username(new_username)
        if existing and existing.id != user.id:
            raise UsernameAlreadyExistsError()
        user.username = new_username
        await self._users.flush()
        return user

    async def update_profile(self, user: User, data: UpdateProfileRequest) -> User:
        if data.full_name is not None:
            user.full_name = data.full_name
        await self._users.flush()
        return user

    async def delete_user(self, user: User, current_password: str) -> None:
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError(message="Current password is incorrect")
        await self._send_account_data_export(user)
        await self._users.delete(user)
        logger.info("user.deleted", user_id=str(user.id))

    async def _send_account_data_export(self, user: User) -> None:
        """Emails the user a full XLSX export of their expense data before
        an irreversible account deletion. Unlike other, best-effort
        notifications (password-changed, recurring-expense-created), a
        failure here must block the deletion rather than being swallowed —
        deleting the account anyway would silently destroy data with no
        way to recover it. Raises `AccountDataExportFailedError` (503) if
        delivery is not confirmed after every retry.
        """
        body, filename, content_type = await self._export.export_bytes(
            user,
            export_format="xlsx",
            start_date=None,
            end_date=None,
            category_ids=None,
            min_amount=None,
            max_amount=None,
            search=None,
        )
        html_body = render_template(
            "account_deletion_export.html", username=user.full_name or user.username
        )
        delivered = await self._email_delivery.send(
            to=user.email,
            subject="Your Spenza expense data (account deletion)",
            html_body=html_body,
            attachments=[EmailAttachment(filename=filename, content=body, mime_type=content_type)],
        )
        if not delivered:
            raise AccountDataExportFailedError()

    # ── Admin ─────────────────────────────────────────────────────────────

    async def list_users(self, *, page: int, page_size: int) -> tuple[list[User], int]:
        offset = (page - 1) * page_size
        users = await self._users.list_all(offset=offset, limit=page_size)
        total = await self._users.count_all()
        return users, total

    async def get_user_by_id(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    async def set_user_active(
        self, user_id: uuid.UUID, is_active: bool, *, acting_admin_id: uuid.UUID
    ) -> User:
        if user_id == acting_admin_id:
            raise CannotModifyOwnAccountError()
        user = await self.get_user_by_id(user_id)
        user.is_active = is_active
        await self._users.flush()
        logger.info("admin.user.active_changed", user_id=str(user.id), is_active=is_active)
        return user

    async def unlock_user(self, user_id: uuid.UUID) -> User:
        user = await self.get_user_by_id(user_id)
        user.failed_login_attempts = 0
        user.locked_until = None
        await self._users.flush()
        logger.info("admin.user.unlocked", user_id=str(user.id))
        return user

    async def delete_user_by_admin(self, user_id: uuid.UUID, *, acting_admin_id: uuid.UUID) -> None:
        if user_id == acting_admin_id:
            raise CannotModifyOwnAccountError()
        user = await self.get_user_by_id(user_id)
        await self._send_account_data_export(user)
        await self._users.delete(user)
        logger.info("admin.user.deleted", user_id=str(user.id))

    async def update_user_role(self, user_id: uuid.UUID, role: UserRole) -> User:
        """No self-modification guard here (unlike `set_user_active`/
        `delete_user_by_admin`): demoting yourself doesn't lock you out of
        your own account, only of the admin API, and another admin can
        always re-promote you. The only thing actually guarded against —
        same as the CLI's `demote_admin` — is demoting the *last* admin,
        which would lock everyone out of the admin API entirely.
        """
        user = await self.get_user_by_id(user_id)
        is_demotion = user.role is UserRole.ADMIN and role is UserRole.USER
        if is_demotion and await self._users.count_by_role(UserRole.ADMIN) <= 1:
            raise CannotDemoteLastAdminError()
        user.role = role
        await self._users.flush()
        logger.info("admin.user.role_changed", user_id=str(user.id), role=str(role))
        return user

    async def list_sessions_for_user(self, user_id: uuid.UUID) -> list[RefreshSession]:
        await self.get_user_by_id(user_id)
        return await self._refresh_sessions.list_active_for_user(user_id)

    async def admin_revoke_sessions(self, user_id: uuid.UUID) -> int:
        await self.get_user_by_id(user_id)
        revoked = await self._refresh_sessions.revoke_all_for_user(user_id)
        await self._refresh_sessions.flush()
        logger.info("admin.user.sessions_revoked", user_id=str(user_id), revoked=revoked)
        return revoked

    async def list_active_user_ids(self) -> list[uuid.UUID]:
        return await self._users.list_active_ids()

    async def get_many_by_id(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
        return await self._users.get_many_by_id(user_ids)


# ── Maintenance ───────────────────────────────────────────────────────────


# Arbitrary, stable key namespacing this job's Postgres advisory lock. Pick a
# new constant for each future scheduled job so they don't collide.
_OTP_CLEANUP_LOCK_KEY = 727_001


async def cleanup_expired_otps(session: AsyncSession) -> int:
    """Delete `email_otps` rows old enough that neither the OTP itself nor
    any `reset_token` derived from it could still be valid, and commit.

    A verified password-reset OTP survives until `reset-password` completes,
    and its `reset_token` is minted with a *fresh* `OTP_EXPIRE_MINUTES`
    window starting at verification time — later than the OTP row's own
    `expires_at`. Doubling the retention window (measured from `created_at`)
    guarantees this never deletes a row whose `reset_token` could still be
    redeemed. Called from `scripts/cleanup.py` and the unified daily
    housekeeping job in `src.core.cleanup`.

    Guarded by a Postgres advisory lock scoped to the current transaction:
    with more than one worker process (or an external cron firing at the
    same moment as the in-app task), only the caller that acquires the lock
    runs the sweep — everyone else returns 0 immediately instead of racing
    the same DELETE. No-op on SQLite (the test suite's dialect), which has
    no advisory locks and no concurrent workers to guard against.
    """
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        acquired = await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _OTP_CLEANUP_LOCK_KEY}
        )
        if not acquired:
            logger.info("otp_cleanup.skipped_lock_held")
            await session.commit()
            return 0

    cutoff = datetime.now(UTC) - timedelta(minutes=settings.OTP_EXPIRE_MINUTES * 2)
    deleted = await EmailOTPRepository(session).delete_older_than(cutoff)
    await session.commit()
    return deleted
