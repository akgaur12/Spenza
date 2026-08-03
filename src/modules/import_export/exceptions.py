"""Domain-specific exceptions for the `import_export` module.

Row-level validation problems (invalid date, category not found, ...) are
*not* exceptions — they're reported as `ImportRowError` entries in the
preview response (see `schemas.py`) so one bad row never fails the whole
request. These exceptions are for file- and session-level failures that
legitimately stop the request outright.
"""

from src.core.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)


class UnsupportedFileTypeError(BadRequestError):
    """Only .csv and .xlsx files are supported for import."""

    error_code = "UNSUPPORTED_FILE_TYPE"


class ImportFileTooLargeError(BadRequestError):
    """The uploaded file exceeds the maximum allowed size."""

    error_code = "IMPORT_FILE_TOO_LARGE"


class ImportRowLimitExceededError(BadRequestError):
    """The uploaded file contains more data rows than the maximum allowed."""

    error_code = "IMPORT_ROW_LIMIT_EXCEEDED"


class ImportFileEmptyError(BadRequestError):
    """The uploaded file contains no data rows."""

    error_code = "IMPORT_FILE_EMPTY"


class ImportMissingColumnsError(BadRequestError):
    """The uploaded file is missing one or more required columns."""

    error_code = "IMPORT_MISSING_COLUMNS"


class ImportFileUnreadableError(BadRequestError):
    """The uploaded file could not be parsed as the declared file type."""

    error_code = "IMPORT_FILE_UNREADABLE"


class ImportSessionNotFoundError(NotFoundError):
    """No import session owned by the current user matches this token."""

    error_code = "IMPORT_SESSION_NOT_FOUND"


class ImportSessionExpiredError(UnprocessableEntityError):
    """The import session has expired; re-run the preview."""

    error_code = "IMPORT_SESSION_EXPIRED"


class ImportSessionAlreadyConfirmedError(ConflictError):
    """This import session has already been confirmed."""

    error_code = "IMPORT_SESSION_ALREADY_CONFIRMED"


class ImportNoValidRowsError(BadRequestError):
    """The import session has no valid rows to import."""

    error_code = "IMPORT_NO_VALID_ROWS"


class ImportConfirmationFailedError(ConflictError):
    """A previously validated row could no longer be imported (e.g. its
    category was deactivated after preview); the import was rolled back.
    """

    error_code = "IMPORT_CONFIRMATION_FAILED"
