"""Domain-specific exceptions for the `expenses` module."""

from src.core.exceptions import NotFoundError


class ExpenseNotFoundError(NotFoundError):
    """No expense owned by the current user matches the given identifier."""

    error_code = "EXPENSE_NOT_FOUND"
