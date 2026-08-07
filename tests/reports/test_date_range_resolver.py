"""Unit tests for `src.modules.reports.date_range_resolver`.

All pure functions taking synthetic `today`/`ReportRequest` values — no
database, no real wall clock — so every calendar edge case (leap years,
year rollovers, partial custom-range months) is directly testable.
"""

from datetime import date

import pytest

from src.modules.reports.date_range_resolver import (
    MAX_CUSTOM_RANGE_DAYS,
    ResolvedDateRange,
    month_buckets,
    previous_period,
    resolve_date_range,
)
from src.modules.reports.exceptions import (
    FutureReportPeriodError,
    InvalidReportDateRangeError,
    InvalidReportQuarterError,
    InvalidReportYearError,
    MissingReportFieldsError,
    ReportDateRangeTooLargeError,
)
from src.modules.reports.schemas import ReportFormat, ReportRequest, ReportType

TODAY = date(2026, 8, 6)


# ── Monthly ──────────────────────────────────────────────────────────────


def test_monthly_resolves_full_calendar_month() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    resolved = resolve_date_range(request, TODAY)
    assert resolved == ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))


def test_monthly_handles_february_leap_year() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, year=2024, month=2)
    resolved = resolve_date_range(request, date(2024, 12, 1))
    assert resolved.end_date == date(2024, 2, 29)


def test_monthly_missing_month_raises() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, year=2026)
    with pytest.raises(MissingReportFieldsError):
        resolve_date_range(request, TODAY)


def test_monthly_missing_year_raises() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, month=7)
    with pytest.raises(MissingReportFieldsError):
        resolve_date_range(request, TODAY)


def test_monthly_year_too_far_in_future_raises() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, year=2027, month=1)
    with pytest.raises(InvalidReportYearError):
        resolve_date_range(request, TODAY)


def test_monthly_year_before_min_raises() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, year=1999, month=1)
    with pytest.raises(InvalidReportYearError):
        resolve_date_range(request, TODAY)


def test_monthly_future_month_in_current_year_raises() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=12)
    with pytest.raises(FutureReportPeriodError):
        resolve_date_range(request, TODAY)


def test_monthly_current_in_progress_month_is_allowed() -> None:
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=8)
    resolved = resolve_date_range(request, TODAY)
    assert resolved.start_date == date(2026, 8, 1)


# ── Quarterly ────────────────────────────────────────────────────────────


def test_quarterly_resolves_q3() -> None:
    request = ReportRequest(type=ReportType.QUARTERLY, year=2026, quarter=3)
    resolved = resolve_date_range(request, TODAY)
    assert resolved == ResolvedDateRange(date(2026, 7, 1), date(2026, 9, 30))


def test_quarterly_missing_quarter_raises() -> None:
    request = ReportRequest(type=ReportType.QUARTERLY, year=2026)
    with pytest.raises(MissingReportFieldsError):
        resolve_date_range(request, TODAY)


def test_quarterly_out_of_schema_quarter_raises() -> None:
    """`quarter` is schema-constrained to 1-4, so this path is normally
    unreachable through the API — exercised directly via `model_construct`
    (bypassing validation) to cover the resolver's own defensive check.
    """
    request = ReportRequest.model_construct(
        type=ReportType.QUARTERLY,
        format=ReportFormat.PDF,
        year=2026,
        quarter=5,
        month=None,
        start_date=None,
        end_date=None,
    )
    with pytest.raises(InvalidReportQuarterError):
        resolve_date_range(request, TODAY)


def test_quarterly_future_quarter_raises() -> None:
    request = ReportRequest(type=ReportType.QUARTERLY, year=2026, quarter=4)
    with pytest.raises(FutureReportPeriodError):
        resolve_date_range(request, TODAY)


# ── Yearly ───────────────────────────────────────────────────────────────


def test_yearly_resolves_full_year() -> None:
    request = ReportRequest(type=ReportType.YEARLY, year=2025)
    resolved = resolve_date_range(request, TODAY)
    assert resolved == ResolvedDateRange(date(2025, 1, 1), date(2025, 12, 31))


def test_yearly_current_year_is_allowed() -> None:
    request = ReportRequest(type=ReportType.YEARLY, year=2026)
    resolved = resolve_date_range(request, TODAY)
    assert resolved.start_date == date(2026, 1, 1)


def test_yearly_future_year_raises() -> None:
    request = ReportRequest(type=ReportType.YEARLY, year=2027)
    with pytest.raises(InvalidReportYearError):
        resolve_date_range(request, TODAY)


def test_yearly_missing_year_raises() -> None:
    request = ReportRequest(type=ReportType.YEARLY)
    with pytest.raises(MissingReportFieldsError):
        resolve_date_range(request, TODAY)


# ── Custom ───────────────────────────────────────────────────────────────


def test_custom_resolves_given_range() -> None:
    request = ReportRequest(
        type=ReportType.CUSTOM, start_date=date(2026, 1, 1), end_date=date(2026, 6, 30)
    )
    resolved = resolve_date_range(request, TODAY)
    assert resolved == ResolvedDateRange(date(2026, 1, 1), date(2026, 6, 30))


def test_custom_missing_dates_raises() -> None:
    request = ReportRequest(type=ReportType.CUSTOM)
    with pytest.raises(MissingReportFieldsError):
        resolve_date_range(request, TODAY)


def test_custom_start_after_end_raises() -> None:
    request = ReportRequest(
        type=ReportType.CUSTOM, start_date=date(2026, 6, 30), end_date=date(2026, 1, 1)
    )
    with pytest.raises(InvalidReportDateRangeError):
        resolve_date_range(request, TODAY)


def test_custom_range_too_large_raises() -> None:
    request = ReportRequest(
        type=ReportType.CUSTOM,
        start_date=date(2000, 1, 1),
        end_date=date(2000, 1, 1).replace(year=2000 + (MAX_CUSTOM_RANGE_DAYS // 365) + 2),
    )
    with pytest.raises(ReportDateRangeTooLargeError):
        resolve_date_range(request, TODAY)


def test_custom_future_range_raises() -> None:
    request = ReportRequest(
        type=ReportType.CUSTOM, start_date=date(2026, 9, 1), end_date=date(2026, 9, 30)
    )
    with pytest.raises(FutureReportPeriodError):
        resolve_date_range(request, TODAY)


# ── previous_period ──────────────────────────────────────────────────────


def test_previous_period_is_equal_length_trailing_window() -> None:
    # Jul 1-31 spans 31 days; May has only 30, so an equal-length window
    # ending 30 Jun must start 31 May (31 May..30 Jun inclusive = 31 days),
    # not 1 Jun (which would only be a 30-day window).
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    previous = previous_period(resolved)
    assert previous == ResolvedDateRange(date(2026, 5, 31), date(2026, 6, 30))
    assert previous.span_days == resolved.span_days


def test_previous_period_single_day() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 15), date(2026, 7, 15))
    previous = previous_period(resolved)
    assert previous == ResolvedDateRange(date(2026, 7, 14), date(2026, 7, 14))


# ── month_buckets ─────────────────────────────────────────────────────────


def test_month_buckets_single_month() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    buckets = month_buckets(resolved)
    assert buckets == [ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))]


def test_month_buckets_quarter_yields_three_months() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 9, 30))
    buckets = month_buckets(resolved)
    assert [b.start_date.month for b in buckets] == [7, 8, 9]


def test_month_buckets_year_yields_twelve_months() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    buckets = month_buckets(resolved)
    assert len(buckets) == 12
    assert buckets[0].start_date == date(2026, 1, 1)
    assert buckets[-1].end_date == date(2026, 12, 31)


def test_month_buckets_clips_partial_custom_range() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 15), date(2026, 2, 10))
    buckets = month_buckets(resolved)
    assert buckets == [
        ResolvedDateRange(date(2026, 1, 15), date(2026, 1, 31)),
        ResolvedDateRange(date(2026, 2, 1), date(2026, 2, 10)),
    ]


def test_month_buckets_caps_at_max_buckets() -> None:
    resolved = ResolvedDateRange(date(2020, 1, 1), date(2026, 12, 31))
    buckets = month_buckets(resolved, max_buckets=12)
    assert len(buckets) == 12
