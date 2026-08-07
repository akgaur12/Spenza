"""Unit tests for the pure helper functions in `src.modules.reports.service`
— heatmap-year resolution and filename generation. No database, no HTTP:
these are plain functions of `ReportType`/`ResolvedDateRange`.
"""

from datetime import date

from src.modules.reports.date_range_resolver import ResolvedDateRange
from src.modules.reports.schemas import ReportType
from src.modules.reports.service import (
    CUSTOM_HEATMAP_MAX_SPAN_DAYS,
    _report_filename,
    _resolve_heatmap_years,
)


def test_heatmap_years_single_year() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    assert _resolve_heatmap_years(ReportType.MONTHLY, resolved) == [2026]


def test_heatmap_years_spans_year_boundary() -> None:
    resolved = ResolvedDateRange(date(2025, 11, 1), date(2026, 2, 1))
    assert _resolve_heatmap_years(ReportType.CUSTOM, resolved) == [2025, 2026]


def test_heatmap_years_none_for_very_large_custom_range() -> None:
    resolved = ResolvedDateRange(date(2020, 1, 1), date(2020, 1, 1).replace(year=2020 + 5))
    assert resolved.span_days > CUSTOM_HEATMAP_MAX_SPAN_DAYS
    assert _resolve_heatmap_years(ReportType.CUSTOM, resolved) is None


def test_heatmap_years_large_span_allowed_for_yearly() -> None:
    """The size cap only applies to `custom` — a yearly report's own span is
    always ~365 days and must still get its heatmap.
    """
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    assert _resolve_heatmap_years(ReportType.YEARLY, resolved) == [2026]


def test_filename_monthly() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    assert _report_filename(ReportType.MONTHLY, resolved) == "monthly-report-2026-07.pdf"


def test_filename_quarterly() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 9, 30))
    assert _report_filename(ReportType.QUARTERLY, resolved) == "quarterly-report-2026-Q3.pdf"


def test_filename_yearly() -> None:
    resolved = ResolvedDateRange(date(2025, 1, 1), date(2025, 12, 31))
    assert _report_filename(ReportType.YEARLY, resolved) == "yearly-report-2025.pdf"


def test_filename_custom() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 6, 30))
    assert (
        _report_filename(ReportType.CUSTOM, resolved)
        == "custom-report-2026-01-01_to_2026-06-30.pdf"
    )
