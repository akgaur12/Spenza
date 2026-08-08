"""Domain-specific exceptions for the `notifications` module."""

from src.core.exceptions import NotFoundError, ServiceUnavailableError


class NotificationNotFoundError(NotFoundError):
    """No notification owned by the current user matches the given identifier."""

    error_code = "NOTIFICATION_NOT_FOUND"


class EmailDeliveryFailedError(ServiceUnavailableError):
    """The email provider could not deliver the message after every retry."""

    error_code = "EMAIL_DELIVERY_FAILED"
