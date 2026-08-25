"""Shared date-range resolution for tools that accept an optional
`start_date`/`end_date` pair.

Builds on the same pure helpers `reports` already uses for period math
(`ResolvedDateRange`, `previous_period`) rather than re-implementing
period-comparison logic — see `reports/date_range_resolver.py`.
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from src.core.periods import end_of_month, start_of_month
from src.core.timezone import APP_TIMEZONE, local_midnight_utc
from src.modules.reports.date_range_resolver import ResolvedDateRange, previous_period

_PERCENT = Decimal("0.01")


def resolve_range(start: date | None, end: date | None) -> ResolvedDateRange:
    """Both given -> used as-is. Only one given -> the other end filled in
    sensibly (a start with no end runs through today; an end with no start
    runs from the start of that end date's month). Neither given -> the
    current calendar month so far.
    """
    now_local = datetime.now(APP_TIMEZONE)
    today = now_local.date()
    if start is not None and end is not None:
        return ResolvedDateRange(start, end)
    if start is not None:
        return ResolvedDateRange(start, today)
    if end is not None:
        end_local = datetime(end.year, end.month, end.day, tzinfo=APP_TIMEZONE)
        return ResolvedDateRange(start_of_month(end_local).date(), end)
    return ResolvedDateRange(start_of_month(now_local).date(), end_of_month(now_local))


def to_utc_bounds(resolved: ResolvedDateRange) -> tuple[datetime, datetime, int]:
    """`[start_utc, end_utc)` plus day count, ready for
    `DashboardService.get_range_summary`.
    """
    start_utc = local_midnight_utc(resolved.start_date)
    end_utc = local_midnight_utc(resolved.end_date + timedelta(days=1))
    return start_utc, end_utc, resolved.span_days


def previous(resolved: ResolvedDateRange) -> ResolvedDateRange:
    return previous_period(resolved)


def percentage_change(current: Decimal, previous_total: Decimal) -> float | None:
    """`None` when `previous_total` is zero and `current` isn't — percentage
    growth from a zero base is undefined, same rule as `dashboard.service.
    _compare_months`.
    """
    if previous_total == 0:
        return 0.0 if current == 0 else None
    return float(
        ((current - previous_total) / previous_total * 100).quantize(
            _PERCENT, rounding=ROUND_HALF_UP
        )
    )
