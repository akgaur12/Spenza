from src.core.exceptions import BadRequestError


class IncompleteDateRangeError(BadRequestError):
    """Provide both start_date and end_date, or neither."""

    error_code = "INCOMPLETE_DATE_RANGE"


class InvalidDateRangeError(BadRequestError):
    """start_date must be on or before end_date."""

    error_code = "INVALID_DATE_RANGE"


class DateRangeTooLargeError(BadRequestError):
    """The requested date range exceeds the maximum supported span."""

    error_code = "DATE_RANGE_TOO_LARGE"


class InvalidYearError(BadRequestError):
    """The requested year is outside the supported range."""

    error_code = "INVALID_YEAR"
