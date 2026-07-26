"""Application-wide exception hierarchy.

Every raised `AppError` is translated by the handler registered in
`src/app.py` into the standard `ErrorResponse` envelope, so business logic
never needs to touch a `Response`/`JSONResponse` object directly.
"""

from typing import Any


class AppError(Exception):
    """Base class for all expected, handled application errors."""

    status_code: int = 400
    error_code: str = "APP_ERROR"

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.__doc__ or "An error occurred"
        self.error_code = error_code or self.error_code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)


class BadRequestError(AppError):
    """The request was malformed or failed validation."""

    status_code = 400
    error_code = "BAD_REQUEST"


class UnauthorizedError(AppError):
    """Authentication is required or has failed."""

    status_code = 401
    error_code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    """The authenticated user may not perform this action."""

    status_code = 403
    error_code = "FORBIDDEN"


class NotFoundError(AppError):
    """The requested resource does not exist."""

    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(AppError):
    """The request conflicts with the current state of the resource."""

    status_code = 409
    error_code = "CONFLICT"


class UnprocessableEntityError(AppError):
    """The request was well-formed but semantically invalid."""

    status_code = 422
    error_code = "UNPROCESSABLE_ENTITY"


class TooManyRequestsError(AppError):
    """The client has exceeded the allowed request rate."""

    status_code = 429
    error_code = "TOO_MANY_REQUESTS"


class InternalServerError(AppError):
    """An unexpected internal error occurred."""

    status_code = 500
    error_code = "INTERNAL_ERROR"


class ServiceUnavailableError(AppError):
    """A required downstream dependency (e.g. the database) is unreachable."""

    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"
