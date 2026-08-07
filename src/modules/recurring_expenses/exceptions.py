"""Domain-specific exceptions for the `recurring_expenses` module."""

from src.core.exceptions import BadRequestError, ConflictError, NotFoundError


class RecurringExpenseNotFoundError(NotFoundError):
    """No recurring expense owned by the current user matches the given identifier."""

    error_code = "RECURRING_EXPENSE_NOT_FOUND"


class InvalidRecurringExpenseDateRangeError(BadRequestError):
    """`end_date` must be on or after `start_date`."""

    error_code = "INVALID_RECURRING_EXPENSE_DATE_RANGE"


class RecurringExpenseNotActiveError(ConflictError):
    """The action requires the recurring expense to currently be active."""

    error_code = "RECURRING_EXPENSE_NOT_ACTIVE"


class RecurringExpenseNotPausedError(ConflictError):
    """`resume` requires the recurring expense to currently be paused."""

    error_code = "RECURRING_EXPENSE_NOT_PAUSED"


class RecurringExpenseTerminalStateError(ConflictError):
    """The recurring expense is completed or cancelled and can no longer be modified."""

    error_code = "RECURRING_EXPENSE_TERMINAL_STATE"


class InvalidRecurringExpenseStatusError(BadRequestError):
    """`status` may only be set to `cancelled` via update; other transitions
    have their own dedicated endpoints (`/pause`, `/resume`) or are
    system-managed (`completed`).
    """

    error_code = "INVALID_RECURRING_EXPENSE_STATUS"
