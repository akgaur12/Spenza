"""Resolves a `ReportRequest` into concrete calendar-day boundaries.

Every date calculation a report needs — the requested period itself, its
same-length "previous period" for comparison, and the calendar-month slices
used by the monthly category analysis / heatmap sections — lives here as
plain, dependency-free functions, so they're unit-testable against synthetic
`today` values without a database or the real wall clock. Mirrors
`src.core.periods` in spirit, but works in caller-supplied plain `date`s
rather than app-timezone `datetime`s, since a report period is defined by
calendar year/month/quarter numbers, not "now".
"""

from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from src.modules.reports.exceptions import (
    FutureReportPeriodError,
    InvalidReportDateRangeError,
    InvalidReportQuarterError,
    InvalidReportYearError,
    MissingReportFieldsError,
    ReportDateRangeTooLargeError,
)
from src.modules.reports.schemas import ReportRequest, ReportType

MIN_REPORT_YEAR = 2000

# A report can span at most this many days — bounds a pathological custom
# range (e.g. a decades-long span) the same way analytics bounds trends.
MAX_CUSTOM_RANGE_DAYS = 366 * 5

# Bounds the number of calendar-month slices `month_buckets()` will return —
# a report already can't exceed `MAX_CUSTOM_RANGE_DAYS`, but this keeps the
# monthly category analysis / per-month heatmap grids from ballooning to
# dozens of sections even for a multi-year custom range.
MAX_MONTH_BUCKETS = 12


@dataclass(frozen=True, slots=True)
class ResolvedDateRange:
    start_date: date
    end_date: date

    @property
    def span_days(self) -> int:
        return (self.end_date - self.start_date).days + 1


def _validate_year(year: int | None, current_year: int) -> int:
    if year is None:
        raise MissingReportFieldsError("year is required for this report type.")
    if not (MIN_REPORT_YEAR <= year <= current_year):
        raise InvalidReportYearError(f"year must be between {MIN_REPORT_YEAR} and {current_year}.")
    return year


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _resolve_monthly(request: ReportRequest, current_year: int) -> ResolvedDateRange:
    year = _validate_year(request.year, current_year)
    if request.month is None:
        raise MissingReportFieldsError("month is required for a monthly report.")
    return ResolvedDateRange(date(year, request.month, 1), _month_end(year, request.month))


def _resolve_quarterly(request: ReportRequest, current_year: int) -> ResolvedDateRange:
    year = _validate_year(request.year, current_year)
    if request.quarter is None:
        raise MissingReportFieldsError("quarter is required for a quarterly report.")
    if not (1 <= request.quarter <= 4):
        raise InvalidReportQuarterError()
    start_month = (request.quarter - 1) * 3 + 1
    end_month = start_month + 2
    return ResolvedDateRange(date(year, start_month, 1), _month_end(year, end_month))


def _resolve_yearly(request: ReportRequest, current_year: int) -> ResolvedDateRange:
    year = _validate_year(request.year, current_year)
    return ResolvedDateRange(date(year, 1, 1), date(year, 12, 31))


def _resolve_custom(request: ReportRequest, _current_year: int) -> ResolvedDateRange:
    if request.start_date is None or request.end_date is None:
        raise MissingReportFieldsError("start_date and end_date are required for a custom report.")
    if request.start_date > request.end_date:
        raise InvalidReportDateRangeError()
    resolved = ResolvedDateRange(request.start_date, request.end_date)
    if resolved.span_days > MAX_CUSTOM_RANGE_DAYS:
        raise ReportDateRangeTooLargeError(
            f"Date range too large: {resolved.span_days} days requested, maximum is "
            f"{MAX_CUSTOM_RANGE_DAYS} days (~{MAX_CUSTOM_RANGE_DAYS // 366} years)."
        )
    return resolved


_RESOLVERS: dict[ReportType, Callable[[ReportRequest, int], ResolvedDateRange]] = {
    ReportType.MONTHLY: _resolve_monthly,
    ReportType.QUARTERLY: _resolve_quarterly,
    ReportType.YEARLY: _resolve_yearly,
    ReportType.CUSTOM: _resolve_custom,
}


def resolve_date_range(request: ReportRequest, today: date) -> ResolvedDateRange:
    resolved = _RESOLVERS[request.type](request, today.year)
    if resolved.start_date > today:
        raise FutureReportPeriodError(
            "The requested period is entirely in the future; there is nothing to report on yet."
        )
    return resolved


def previous_period(resolved: ResolvedDateRange) -> ResolvedDateRange:
    """The equal-length window immediately preceding `resolved`, used for the
    executive summary's period-over-period comparison. A trailing window of
    the same length is the one comparison rule that applies identically to
    every report type — a calendar-aware "previous month/quarter/year" would
    need a different rule per type, which the "one pipeline" design avoids.
    """
    span = resolved.span_days
    end = resolved.start_date - timedelta(days=1)
    start = end - timedelta(days=span - 1)
    return ResolvedDateRange(start, end)


def month_buckets(
    resolved: ResolvedDateRange, max_buckets: int = MAX_MONTH_BUCKETS
) -> list[ResolvedDateRange]:
    """Every calendar month `resolved` overlaps, each clipped to `resolved`'s
    own boundaries, in chronological order — used by the monthly category
    analysis and per-month heatmap grids. Capped at `max_buckets`; callers
    should treat a truncated result as "summarize/omit" territory rather
    than silently showing only the first N months.
    """
    buckets: list[ResolvedDateRange] = []
    cursor = date(resolved.start_date.year, resolved.start_date.month, 1)
    while cursor <= resolved.end_date and len(buckets) < max_buckets:
        month_start = max(cursor, resolved.start_date)
        month_end = min(_month_end(cursor.year, cursor.month), resolved.end_date)
        buckets.append(ResolvedDateRange(month_start, month_end))
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return buckets
