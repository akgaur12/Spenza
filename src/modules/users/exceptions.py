"""Domain-specific exceptions for the `users` module."""

from src.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    TooManyRequestsError,
    UnauthorizedError,
)


class EmailAlreadyExistsError(ConflictError):
    """An account with this email already exists."""

    error_code = "EMAIL_ALREADY_EXISTS"


class UsernameAlreadyExistsError(ConflictError):
    """This username is already taken."""

    error_code = "USERNAME_ALREADY_EXISTS"


class WeakPasswordError(BadRequestError):
    """The password does not meet the complexity requirements."""

    error_code = "WEAK_PASSWORD"


class InvalidCredentialsError(UnauthorizedError):
    """The email/username or password is incorrect."""

    error_code = "INVALID_CREDENTIALS"


class EmailNotVerifiedError(ForbiddenError):
    """The account's email has not been verified yet."""

    error_code = "EMAIL_NOT_VERIFIED"


class AccountInactiveError(ForbiddenError):
    """The account has been deactivated."""

    error_code = "ACCOUNT_INACTIVE"


class AccountLockedError(TooManyRequestsError):
    """The account is temporarily locked due to repeated failed logins."""

    error_code = "ACCOUNT_LOCKED"


class UserNotFoundError(NotFoundError):
    """No user matches the given identifier."""

    error_code = "USER_NOT_FOUND"


class InvalidOTPError(BadRequestError):
    """The provided OTP is incorrect."""

    error_code = "INVALID_OTP"


class OTPExpiredError(BadRequestError):
    """The OTP has expired; request a new one."""

    error_code = "OTP_EXPIRED"


class OTPAttemptsExceededError(TooManyRequestsError):
    """Too many incorrect OTP attempts; request a new OTP."""

    error_code = "OTP_ATTEMPTS_EXCEEDED"


class OTPAlreadyVerifiedError(BadRequestError):
    """This OTP has already been used."""

    error_code = "OTP_ALREADY_VERIFIED"


class OTPResendCooldownError(TooManyRequestsError):
    """A new OTP was requested too soon after the last one."""

    error_code = "OTP_RESEND_COOLDOWN"


class InvalidRefreshTokenError(UnauthorizedError):
    """The refresh token is missing, malformed, or unknown."""

    error_code = "INVALID_REFRESH_TOKEN"


class RefreshTokenExpiredError(UnauthorizedError):
    """The refresh token has expired; the user must log in again."""

    error_code = "REFRESH_TOKEN_EXPIRED"


class RefreshTokenRevokedError(UnauthorizedError):
    """The refresh token has been revoked (rotated, logged out, or reset)."""

    error_code = "REFRESH_TOKEN_REVOKED"


class InvalidAccessTokenError(UnauthorizedError):
    """The access token is missing, malformed, expired, or revoked."""

    error_code = "INVALID_ACCESS_TOKEN"


class InvalidResetTokenError(BadRequestError):
    """The password reset token is invalid, expired, or already used."""

    error_code = "INVALID_RESET_TOKEN"


class AdminPrivilegesRequiredError(ForbiddenError):
    """The authenticated user does not have admin privileges."""

    error_code = "ADMIN_PRIVILEGES_REQUIRED"


class CannotModifyOwnAccountError(BadRequestError):
    """An admin cannot deactivate or delete their own account via this API."""

    error_code = "CANNOT_MODIFY_OWN_ACCOUNT"


class AccountDataExportFailedError(ServiceUnavailableError):
    """The pre-deletion expense-data export email could not be delivered
    after every retry; the account was not deleted.
    """

    error_code = "ACCOUNT_DATA_EXPORT_FAILED"
