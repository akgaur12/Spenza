"""Domain-specific exceptions for the `reports` module.

Row/field-level request shape is enforced by Pydantic on `ReportRequest`
(e.g. `month` must be 1-12); everything here is a *cross-field* or
*business-rule* validation problem that only the date range resolver or
report service can detect.
"""

from src.core.exceptions import BadRequestError, InternalServerError, ServiceUnavailableError


class MissingReportFieldsError(BadRequestError):
    """A field required for this report `type` was not provided."""

    error_code = "MISSING_REPORT_FIELDS"


class InvalidReportYearError(BadRequestError):
    """The requested year is outside the supported range."""

    error_code = "INVALID_REPORT_YEAR"


class InvalidReportQuarterError(BadRequestError):
    """`quarter` must be between 1 and 4."""

    error_code = "INVALID_REPORT_QUARTER"


class InvalidReportDateRangeError(BadRequestError):
    """`start_date` must be on or before `end_date`."""

    error_code = "INVALID_REPORT_DATE_RANGE"


class ReportDateRangeTooLargeError(BadRequestError):
    """The requested custom date range exceeds the maximum supported span."""

    error_code = "REPORT_DATE_RANGE_TOO_LARGE"


class FutureReportPeriodError(BadRequestError):
    """The requested period lies entirely in the future; there is nothing to report on yet."""

    error_code = "FUTURE_REPORT_PERIOD"


class ReportGenerationFailedError(InternalServerError):
    """PDF rendering failed unexpectedly."""

    error_code = "REPORT_GENERATION_FAILED"


class ReportEmailDeliveryFailedError(ServiceUnavailableError):
    """The report was generated but could not be emailed after every retry."""

    error_code = "REPORT_EMAIL_DELIVERY_FAILED"
