"""Password hashing, JWT issuance/verification, and OTP hashing primitives.

Kept dependency-free of any HTTP/ORM concerns so it can be unit tested in
isolation and reused by any future module beyond `users`.
"""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from src.core.app_config import settings

_password_hasher = PasswordHasher()


# ── Password hashing (Argon2id) ─────────────────────────────────────────────


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against its Argon2id hash."""
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the stored hash was made with outdated Argon2 parameters."""
    return _password_hasher.check_needs_rehash(password_hash)


# ── JWT access tokens ────────────────────────────────────────────────────────


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class DecodedToken:
    subject: str
    token_type: TokenType
    session_id: str | None
    jti: str
    issued_at: datetime
    expires_at: datetime


class TokenError(Exception):
    """Base class for all token validation failures."""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    """Issue a short-lived JWT access token bound to a refresh session."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sid": str(session_id),
        "type": TokenType.ACCESS.value,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, *, expected_type: TokenType) -> DecodedToken:
    """Decode and validate a JWT, raising `TokenExpiredError`/`TokenInvalidError`."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("Token is invalid") from exc

    if payload.get("type") != expected_type.value:
        raise TokenInvalidError("Unexpected token type")

    try:
        return DecodedToken(
            subject=payload["sub"],
            token_type=TokenType(payload["type"]),
            session_id=payload.get("sid"),
            jti=payload["jti"],
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise TokenInvalidError("Malformed token payload") from exc


def create_action_token(
    *, subject: str, purpose: str, expire_minutes: int, extra_claims: dict[str, Any] | None = None
) -> str:
    """Issue a short-lived, single-purpose JWT not tied to any session
    (e.g. a password-reset token). Distinct from access/refresh tokens.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "purpose": purpose,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_action_token(token: str, *, expected_purpose: str) -> dict[str, Any]:
    """Decode a single-purpose JWT issued by `create_action_token`."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("Token is invalid") from exc

    if payload.get("purpose") != expected_purpose:
        raise TokenInvalidError("Unexpected token purpose")
    return payload


# ── Refresh tokens (opaque, hashed at rest) ─────────────────────────────────


def generate_refresh_token() -> str:
    """Generate a high-entropy, URL-safe opaque refresh token."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(raw_token: str) -> str:
    """Hash a refresh token for storage (SHA-256 is sufficient: input is already
    high-entropy random data, not a low-entropy user secret)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def verify_refresh_token(raw_token: str, token_hash: str) -> bool:
    """Constant-time comparison of a raw refresh token against its stored hash."""
    return secrets.compare_digest(hash_refresh_token(raw_token), token_hash)


# ── OTP ──────────────────────────────────────────────────────────────────────


def generate_otp(length: int | None = None) -> str:
    """Generate a numeric OTP of the configured length using a CSPRNG."""
    digits = length or settings.OTP_LENGTH
    return "".join(str(secrets.randbelow(10)) for _ in range(digits))


def hash_otp(raw_otp: str) -> str:
    """Hash an OTP for storage."""
    return hashlib.sha256(raw_otp.encode("utf-8")).hexdigest()


def verify_otp(raw_otp: str, otp_hash: str) -> bool:
    """Constant-time comparison of a raw OTP against its stored hash."""
    return secrets.compare_digest(hash_otp(raw_otp), otp_hash)
