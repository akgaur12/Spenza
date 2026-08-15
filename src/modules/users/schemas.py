"""Pydantic v2 request/response schemas for the `users` module."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.modules.users.models import UserRole
from src.modules.users.validators import validate_password_strength, validate_username

# ── Auth: signup / OTP ───────────────────────────────────────────────────────


class SignupRequest(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=150)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "jane.doe@example.com",
                "username": "jane_doe",
                "password": "SecureP@ssw0rd!",
                "full_name": "Jane Doe",
            }
        }
    )

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return validate_username(value)

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


class VerifySignupOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=8)

    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "jane.doe@example.com", "otp": "482913"}}
    )


class ResendOTPRequest(BaseModel):
    email: EmailStr

    model_config = ConfigDict(json_schema_extra={"example": {"email": "jane.doe@example.com"}})


# ── Auth: login / tokens ─────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    identifier: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Email address or username",
    )
    password: str = Field(..., min_length=1, max_length=128)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"identifier": "jane.doe@example.com", "password": "SecureP@ssw0rd!"}
        }
    )


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105


# ── User representations ─────────────────────────────────────────────────────


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: EmailStr
    is_verified: bool
    is_active: bool


class UserMe(UserPublic):
    full_name: str | None


class UserProfile(UserMe):
    created_at: datetime
    updated_at: datetime


class SessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime | None


# ── Password management ──────────────────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: EmailStr

    model_config = ConfigDict(json_schema_extra={"example": {"email": "jane.doe@example.com"}})


class VerifyResetOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=8)

    model_config = ConfigDict(
        json_schema_extra={"example": {"email": "jane.doe@example.com", "otp": "482913"}}
    )


class ResetTokenResponse(BaseModel):
    reset_token: str
    expires_in_minutes: int


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=8, max_length=128)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"reset_token": "eyJhbGciOi...", "new_password": "NewSecureP@ss1"}
        }
    )

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "current_password": "OldSecureP@ss1",
                "new_password": "NewSecureP@ss1",
            }
        }
    )

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return validate_password_strength(value)


# ── User profile management ──────────────────────────────────────────────────


class UpdateUsernameRequest(BaseModel):
    new_username: str = Field(..., min_length=3, max_length=30)

    model_config = ConfigDict(json_schema_extra={"example": {"new_username": "jane_updated"}})

    @field_validator("new_username")
    @classmethod
    def _username(cls, value: str) -> str:
        return validate_username(value)


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=150)

    model_config = ConfigDict(json_schema_extra={"example": {"full_name": "Jane Doe"}})


class DeleteUserRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)

    model_config = ConfigDict(
        json_schema_extra={"example": {"current_password": "SecureP@ssw0rd!"}}
    )


# ── Admin ──────────────────────────────────────────────────────────────────


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_verified: bool
    is_active: bool
    failed_login_attempts: int
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedUsersResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
    page: int
    page_size: int


class SetUserActiveRequest(BaseModel):
    is_active: bool

    model_config = ConfigDict(json_schema_extra={"example": {"is_active": False}})


class UpdateUserRoleRequest(BaseModel):
    role: UserRole

    model_config = ConfigDict(json_schema_extra={"example": {"role": "admin"}})


class SessionListResponse(BaseModel):
    items: list[SessionInfo]


class RevokedSessionsResponse(BaseModel):
    revoked: int
