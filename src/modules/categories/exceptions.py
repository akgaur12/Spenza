"""Domain-specific exceptions for the `categories` module."""

from src.core.exceptions import ConflictError, ForbiddenError, NotFoundError


class CategoryNotFoundError(NotFoundError):
    """No visible category matches the given identifier."""

    error_code = "CATEGORY_NOT_FOUND"


class CategoryAlreadyExistsError(ConflictError):
    """A category with this name already exists in this scope."""

    error_code = "CATEGORY_ALREADY_EXISTS"


class SystemCategoryReadOnlyError(ForbiddenError):
    """System categories can only be managed by an administrator."""

    error_code = "SYSTEM_CATEGORY_READ_ONLY"
