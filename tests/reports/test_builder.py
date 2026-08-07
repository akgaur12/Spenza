"""Unit tests for `src.modules.reports.builder.ReportBuilder`.

Constructs `ReportInputs` directly from already-shaped dashboard/analytics
response objects (no database, no HTTP) — the builder's whole job is pure
composition, so these tests only ever check *given exactly this data, does
ReportData come out shaped correctly*.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.modules.analytics.schemas import (
    CalendarHeatmapDay,
    CalendarHeatmapResponse,
    CategoryAnalyticsItem,
    CategoryAnalyticsResponse,
    TrendAnalyticsResponse,
    TrendDataPoint,
    TrendInterval,
)
from src.modules.dashboard.schemas import (
    DashboardCategorySummary,
    LargestExpenseCategory,
    LargestExpenseSummary,
    RangeSummary,
)
from src.modules.import_export.export_formatters import ExportRow
from src.modules.reports.builder import MonthlyCategoryInput, ReportBuilder, ReportInputs
from src.modules.reports.date_range_resolver import ResolvedDateRange, month_buckets
from src.modules.reports.schemas import LineChart, ReportRequest, ReportType, VerticalBarChart
from src.modules.users.models import User, UserRole


def _user(**overrides: object) -> User:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "username": "jane_doe",
        "email": "jane@example.com",
        "password_hash": "x",
        "full_name": "Jane Doe",
        "role": UserRole.USER,
    }
    defaults.update(overrides)
    return User(**defaults)


def _empty_summary() -> RangeSummary:
    return RangeSummary(
        total=Decimal("0.00"),
        expense_count=0,
        daily_average=Decimal("0.00"),
        average_expense=Decimal("0.00"),
        top_category=None,
        largest_expense=None,
    )


def _empty_category_breakdown(resolved: ResolvedDateRange) -> CategoryAnalyticsResponse:
    return CategoryAnalyticsResponse(
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("0.00"),
        expense_count=0,
        categories=[],
    )


def _empty_trends(resolved: ResolvedDateRange) -> TrendAnalyticsResponse:
    return TrendAnalyticsResponse(
        interval=TrendInterval.DAILY,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("0.00"),
        expense_count=0,
        data=[],
    )


def _minimal_inputs(
    resolved: ResolvedDateRange,
    request: ReportRequest,
    **overrides: object,
) -> ReportInputs:
    defaults: dict[str, object] = {
        "user": _user(),
        "request": request,
        "resolved": resolved,
        "generated_at": datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
        "range_summary": _empty_summary(),
        "previous_summary": _empty_summary(),
        "category_breakdown": _empty_category_breakdown(resolved),
        "daily_trend": _empty_trends(resolved),
        "weekly_trend": _empty_trends(resolved),
        "monthly_trend": _empty_trends(resolved),
        "monthly_category": [
            MonthlyCategoryInput(period=b, breakdown=_empty_category_breakdown(b))
            for b in month_buckets(resolved)
        ],
        "heatmap_by_year": {},
        "heatmap_note": None,
        "expenses": [],
    }
    defaults.update(overrides)
    return ReportInputs(**defaults)  # type: ignore[arg-type]


# ── Metadata / period labels ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("report_type", "request_kwargs", "expected_label", "expected_title"),
    [
        (
            ReportType.MONTHLY,
            {"year": 2026, "month": 7},
            "July 2026",
            "Monthly Expense Report",
        ),
        (
            ReportType.QUARTERLY,
            {"year": 2026, "quarter": 3},
            "Q3 2026",
            "Quarterly Expense Report",
        ),
        (ReportType.YEARLY, {"year": 2026}, "2026", "Yearly Expense Report"),
        (
            ReportType.CUSTOM,
            {"start_date": date(2026, 1, 1), "end_date": date(2026, 6, 30)},
            "01-Jan-2026 to 30-Jun-2026",
            "Custom Expense Report",
        ),
    ],
)
def test_period_label_and_title(
    report_type: ReportType,
    request_kwargs: dict[str, object],
    expected_label: str,
    expected_title: str,
) -> None:
    request = ReportRequest(type=report_type, **request_kwargs)
    if report_type is ReportType.MONTHLY:
        resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    elif report_type is ReportType.QUARTERLY:
        resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 9, 30))
    elif report_type is ReportType.YEARLY:
        resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    else:
        resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 6, 30))

    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.metadata.period_label == expected_label
    assert data.metadata.title == expected_title
    assert data.metadata.report_type is report_type


# ── Period-over-period comparison ───────────────────────────────────────


def test_comparison_trend_up_with_percentage() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    inputs = _minimal_inputs(
        resolved,
        request,
        range_summary=RangeSummary(
            total=Decimal("600.00"),
            expense_count=3,
            daily_average=Decimal("19.35"),
            average_expense=Decimal("200.00"),
            top_category=None,
            largest_expense=None,
        ),
        previous_summary=RangeSummary(
            total=Decimal("300.00"),
            expense_count=2,
            daily_average=Decimal("10.00"),
            average_expense=Decimal("150.00"),
            top_category=None,
            largest_expense=None,
        ),
    )
    data = ReportBuilder().build(inputs)
    assert data.summary.comparison.trend == "up"
    assert data.summary.comparison.difference == Decimal("300.00")
    assert data.summary.comparison.percentage_change == 100.0


def test_comparison_trend_down() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    inputs = _minimal_inputs(
        resolved,
        request,
        range_summary=RangeSummary(
            total=Decimal("100.00"),
            expense_count=1,
            daily_average=Decimal("3.23"),
            average_expense=Decimal("100.00"),
            top_category=None,
            largest_expense=None,
        ),
        previous_summary=RangeSummary(
            total=Decimal("400.00"),
            expense_count=2,
            daily_average=Decimal("13.33"),
            average_expense=Decimal("200.00"),
            top_category=None,
            largest_expense=None,
        ),
    )
    data = ReportBuilder().build(inputs)
    assert data.summary.comparison.trend == "down"
    assert data.summary.comparison.difference == Decimal("-300.00")


@pytest.mark.parametrize(
    ("report_type", "request_kwargs", "resolved", "expected_label"),
    [
        (
            ReportType.MONTHLY,
            {"year": 2026, "month": 7},
            ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31)),
            "Previous Month",
        ),
        (
            ReportType.YEARLY,
            {"year": 2026},
            ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31)),
            "Previous Year",
        ),
        (
            ReportType.QUARTERLY,
            {"year": 2026, "quarter": 3},
            ResolvedDateRange(date(2026, 7, 1), date(2026, 9, 30)),
            "Previous Period",
        ),
        (
            ReportType.CUSTOM,
            {"start_date": date(2026, 1, 1), "end_date": date(2026, 6, 30)},
            ResolvedDateRange(date(2026, 1, 1), date(2026, 6, 30)),
            "Previous Period",
        ),
    ],
)
def test_comparison_label_matches_report_type(
    report_type: ReportType,
    request_kwargs: dict[str, object],
    resolved: ResolvedDateRange,
    expected_label: str,
) -> None:
    request = ReportRequest(type=report_type, **request_kwargs)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.summary.comparison_label == expected_label


def test_comparison_zero_base_with_zero_current_is_unchanged() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.summary.comparison.trend == "same"
    assert data.summary.comparison.percentage_change == 0.0


def test_comparison_zero_base_with_positive_current_has_no_percentage() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    inputs = _minimal_inputs(
        resolved,
        request,
        range_summary=RangeSummary(
            total=Decimal("100.00"),
            expense_count=1,
            daily_average=Decimal("3.23"),
            average_expense=Decimal("100.00"),
            top_category=None,
            largest_expense=None,
        ),
    )
    data = ReportBuilder().build(inputs)
    assert data.summary.comparison.trend == "up"
    assert data.summary.comparison.percentage_change is None


# ── Expense table matches export format ─────────────────────────────────


def test_expense_rows_match_export_format() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    inputs = _minimal_inputs(
        resolved,
        request,
        expenses=[
            ExportRow(
                spent_date=date(2026, 7, 15),
                category_name="Food",
                description="Cake",
                amount=Decimal("278.00"),
            )
        ],
    )
    data = ReportBuilder().build(inputs)
    assert len(data.expenses) == 1
    row = data.expenses[0]
    assert row.date == date(2026, 7, 15)
    assert row.day == "Wed"
    assert row.category == "Food"
    assert row.description == "Cake"
    assert row.amount == Decimal("278.00")


# ── Insights ─────────────────────────────────────────────────────────────


def test_insights_pick_highest_month_week_category_and_day() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 8, 31))
    request = ReportRequest(
        type=ReportType.CUSTOM, start_date=resolved.start_date, end_date=resolved.end_date
    )

    category_food = CategoryAnalyticsItem(
        category_id=uuid.uuid4(),
        name="Food",
        icon=None,
        total=Decimal("500.00"),
        expense_count=5,
        percentage=100.0,
        average_expense=Decimal("100.00"),
    )
    category_breakdown = CategoryAnalyticsResponse(
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("500.00"),
        expense_count=5,
        categories=[category_food],
    )

    buckets = month_buckets(resolved)
    monthly_category = [
        MonthlyCategoryInput(
            period=b,
            breakdown=CategoryAnalyticsResponse(
                start_date=b.start_date,
                end_date=b.end_date,
                total_spending=Decimal("300.00") if b.start_date.month == 7 else Decimal("200.00"),
                expense_count=3,
                categories=[],
            ),
        )
        for b in buckets
    ]

    weekly_trends = TrendAnalyticsResponse(
        interval=TrendInterval.WEEKLY,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("500.00"),
        expense_count=5,
        data=[
            TrendDataPoint(
                period="2026-W27",
                start_date=date(2026, 7, 6),
                end_date=date(2026, 7, 12),
                total=Decimal("50.00"),
                expense_count=1,
                average_expense=Decimal("50.00"),
            ),
            TrendDataPoint(
                period="2026-W30",
                start_date=date(2026, 7, 27),
                end_date=date(2026, 8, 2),
                total=Decimal("450.00"),
                expense_count=4,
                average_expense=Decimal("112.50"),
            ),
        ],
    )

    heatmap_by_year = {
        2026: CalendarHeatmapResponse(
            year=2026,
            total_spending=Decimal("500.00"),
            expense_count=5,
            max_daily_spending=Decimal("400.00"),
            data=[
                CalendarHeatmapDay(
                    date=date(2026, 7, 30),
                    month=7,
                    day=30,
                    total=Decimal("400.00"),
                    expense_count=3,
                    is_future=False,
                ),
                # Out-of-range day (outside the resolved Jul-Aug window) with
                # an even larger total — must NOT win "highest spending day".
                CalendarHeatmapDay(
                    date=date(2026, 9, 5),
                    month=9,
                    day=5,
                    total=Decimal("9999.00"),
                    expense_count=1,
                    is_future=False,
                ),
            ],
        )
    }

    inputs = _minimal_inputs(
        resolved,
        request,
        range_summary=RangeSummary(
            total=Decimal("500.00"),
            expense_count=5,
            daily_average=Decimal("8.06"),
            average_expense=Decimal("100.00"),
            top_category=DashboardCategorySummary(
                category_id=category_food.category_id,
                name="Food",
                icon=None,
                total=Decimal("500.00"),
                expense_count=5,
                percentage=100.0,
            ),
            largest_expense=LargestExpenseSummary(
                id=uuid.uuid4(),
                description="Big grocery run",
                amount=Decimal("400.00"),
                spent_at=datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
                category=LargestExpenseCategory(id=uuid.uuid4(), name="Food", icon=None),
            ),
        ),
        category_breakdown=category_breakdown,
        monthly_category=monthly_category,
        weekly_trend=weekly_trends,
        heatmap_by_year=heatmap_by_year,
    )

    data = ReportBuilder().build(inputs)
    insights = data.insights

    assert insights.highest_spending_month_label == "Jul 2026"
    assert insights.highest_spending_month_total == Decimal("300.00")
    assert insights.highest_spending_week_label == "2026-W30"
    assert insights.highest_spending_week_total == Decimal("450.00")
    assert insights.highest_spending_day == date(2026, 7, 30)
    assert insights.highest_spending_day_total == Decimal("400.00")


def test_insights_are_none_when_no_data() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    # Override the default single-bucket `monthly_category` too — otherwise
    # it trivially "wins" as the highest-spending month at zero.
    data = ReportBuilder().build(_minimal_inputs(resolved, request, monthly_category=[]))
    insights = data.insights
    assert insights.highest_spending_month_label is None
    assert insights.highest_spending_week_label is None
    assert insights.highest_spending_day is None


# ── Heatmap ──────────────────────────────────────────────────────────────


def test_heatmap_is_none_without_data() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.heatmap is None


def test_heatmap_note_passed_through_when_omitted() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    request = ReportRequest(
        type=ReportType.CUSTOM, start_date=resolved.start_date, end_date=resolved.end_date
    )
    data = ReportBuilder().build(
        _minimal_inputs(resolved, request, heatmap_note="too large to render")
    )
    assert data.heatmap is None
    assert data.heatmap_note == "too large to render"


def test_heatmap_builds_month_grid_with_correct_padding_and_intensity() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    # 1 Jul 2026 is a Wednesday -> 2 leading padding cells (Mon, Tue).
    heatmap_by_year = {
        2026: CalendarHeatmapResponse(
            year=2026,
            total_spending=Decimal("100.00"),
            expense_count=1,
            max_daily_spending=Decimal("100.00"),
            data=[
                CalendarHeatmapDay(
                    date=date(2026, 7, 15),
                    month=7,
                    day=15,
                    total=Decimal("100.00"),
                    expense_count=1,
                    is_future=False,
                )
            ],
        )
    }
    data = ReportBuilder().build(
        _minimal_inputs(resolved, request, heatmap_by_year=heatmap_by_year)
    )
    assert data.heatmap is not None
    grid = data.heatmap.months[0]
    assert grid.label == "Jul 2026"

    flattened = [cell for week in grid.weeks for cell in week]
    assert flattened[0] is None  # Monday before 1 Jul
    assert flattened[1] is None  # Tuesday before 1 Jul
    first_day = flattened[2]
    assert first_day is not None
    assert first_day.date == date(2026, 7, 1)

    day15 = next(cell for cell in flattened if cell is not None and cell.date == date(2026, 7, 15))
    assert day15.intensity_level == 4
    assert day15.is_in_range is True

    day1 = next(cell for cell in flattened if cell is not None and cell.date == date(2026, 7, 1))
    assert day1.intensity_level == 0


# ── Weekday chart ──────────────────────────────────────────────────────────


def test_weekday_chart_aggregates_by_day_of_week_and_flags_highest() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    # 1 Jul 2026 is a Wednesday; 8 Jul 2026 is also a Wednesday.
    inputs = _minimal_inputs(
        resolved,
        request,
        expenses=[
            ExportRow(
                spent_date=date(2026, 7, 1),
                category_name="Food",
                description="A",
                amount=Decimal("100.00"),
            ),
            ExportRow(
                spent_date=date(2026, 7, 8),
                category_name="Food",
                description="B",
                amount=Decimal("50.00"),
            ),
            ExportRow(
                spent_date=date(2026, 7, 2),
                category_name="Food",
                description="C",
                amount=Decimal("20.00"),
            ),
        ],
    )
    data = ReportBuilder().build(inputs)
    chart = data.weekday_chart
    assert len(chart.bars) == 7
    wednesday = chart.bars[2]
    assert wednesday.label == "Wed"
    assert wednesday.total == Decimal("150.00")
    assert wednesday.is_highest is True
    assert wednesday.bar_pct == 100.0
    assert chart.highest_label == "Wednesday"
    assert data.insights.highest_spending_weekday_label == "Wednesday"


def test_weekday_chart_with_no_expenses_has_no_highest() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.weekday_chart.highest_label is None
    assert all(not bar.is_highest for bar in data.weekday_chart.bars)


# ── Category donut chart ────────────────────────────────────────────────────


def _category(name: str, total: str) -> CategoryAnalyticsItem:
    return CategoryAnalyticsItem(
        category_id=uuid.uuid4(),
        name=name,
        icon=None,
        total=Decimal(total),
        expense_count=1,
        percentage=0.0,
        average_expense=Decimal(total),
    )


def test_category_chart_is_none_without_categories() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.category_chart is None


def test_category_chart_caps_at_five_slices_plus_other() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    categories = [_category(f"Cat{i}", "100.00") for i in range(8)]
    breakdown = CategoryAnalyticsResponse(
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("800.00"),
        expense_count=8,
        categories=categories,
    )
    data = ReportBuilder().build(_minimal_inputs(resolved, request, category_breakdown=breakdown))
    assert data.category_chart is not None
    slices = data.category_chart.slices
    assert len(slices) == 6  # top 5 + "Other"
    assert [s.label for s in slices[:5]] == ["Cat0", "Cat1", "Cat2", "Cat3", "Cat4"]
    assert slices[5].label == "Other"
    assert slices[5].total == Decimal("300.00")  # Cat5 + Cat6 + Cat7
    assert round(sum(s.percentage for s in slices)) == 100


def test_category_chart_no_other_slice_when_five_or_fewer() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    categories = [_category("Food", "100.00"), _category("Travel", "50.00")]
    breakdown = CategoryAnalyticsResponse(
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("150.00"),
        expense_count=2,
        categories=categories,
    )
    data = ReportBuilder().build(_minimal_inputs(resolved, request, category_breakdown=breakdown))
    assert data.category_chart is not None
    assert [s.label for s in data.category_chart.slices] == ["Food", "Travel"]


def test_category_breakdown_table_capped_at_ten() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    categories = [_category(f"Cat{i}", "100.00") for i in range(13)]
    breakdown = CategoryAnalyticsResponse(
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("1300.00"),
        expense_count=13,
        categories=categories,
    )
    data = ReportBuilder().build(_minimal_inputs(resolved, request, category_breakdown=breakdown))
    assert data.category_breakdown is not None
    assert len(data.category_breakdown.categories) == 10
    assert [c.name for c in data.category_breakdown.categories] == [f"Cat{i}" for i in range(10)]


# ── Top expenses ─────────────────────────────────────────────────────────


def test_top_expenses_ranked_descending_and_capped_at_ten() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    expenses = [
        ExportRow(
            spent_date=date(2026, 7, i + 1),
            category_name="Food",
            description=f"Expense {i}",
            amount=Decimal(str(10 * (i + 1))),
        )
        for i in range(13)
    ]
    data = ReportBuilder().build(_minimal_inputs(resolved, request, expenses=expenses))
    assert len(data.top_expenses) == 10
    assert [item.amount for item in data.top_expenses] == [
        Decimal("130"),
        Decimal("120"),
        Decimal("110"),
        Decimal("100"),
        Decimal("90"),
        Decimal("80"),
        Decimal("70"),
        Decimal("60"),
        Decimal("50"),
        Decimal("40"),
    ]
    assert [item.rank for item in data.top_expenses] == list(range(1, 11))


# ── Monthly statistics ───────────────────────────────────────────────────


def test_monthly_statistics_zero_spending_days() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 5))  # 5-day span
    request = ReportRequest(
        type=ReportType.CUSTOM, start_date=resolved.start_date, end_date=resolved.end_date
    )
    expenses = [
        ExportRow(
            spent_date=date(2026, 7, 1),
            category_name="Food",
            description="A",
            amount=Decimal("10.00"),
        ),
        ExportRow(
            spent_date=date(2026, 7, 1),
            category_name="Food",
            description="B",
            amount=Decimal("30.00"),
        ),
        ExportRow(
            spent_date=date(2026, 7, 3),
            category_name="Travel",
            description="C",
            amount=Decimal("20.00"),
        ),
    ]
    data = ReportBuilder().build(_minimal_inputs(resolved, request, expenses=expenses))
    stats = data.monthly_statistics
    assert stats.zero_spending_days == 3  # 5-day span - 2 spending days (Jul 1 and Jul 3)


def test_monthly_statistics_with_no_expenses() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    stats = data.monthly_statistics
    assert stats.zero_spending_days == 31


# ── Narrative insights ───────────────────────────────────────────────────


def test_narrative_insights_cover_comparison_top_category_and_zero_days() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    inputs = _minimal_inputs(
        resolved,
        request,
        range_summary=RangeSummary(
            total=Decimal("600.00"),
            expense_count=3,
            daily_average=Decimal("19.35"),
            average_expense=Decimal("200.00"),
            top_category=DashboardCategorySummary(
                category_id=uuid.uuid4(),
                name="Food",
                icon=None,
                total=Decimal("400.00"),
                expense_count=2,
                percentage=66.7,
            ),
            largest_expense=LargestExpenseSummary(
                id=uuid.uuid4(),
                description="Concert",
                amount=Decimal("300.00"),
                spent_at=datetime(2026, 7, 10, 9, 0, tzinfo=UTC),
                category=LargestExpenseCategory(id=uuid.uuid4(), name="Food", icon=None),
            ),
        ),
        previous_summary=RangeSummary(
            total=Decimal("300.00"),
            expense_count=2,
            daily_average=Decimal("10.00"),
            average_expense=Decimal("150.00"),
            top_category=None,
            largest_expense=None,
        ),
    )
    data = ReportBuilder().build(inputs)
    joined = " ".join(data.narrative_insights)
    assert "₹600.00" in joined
    assert "more than the previous month" in joined
    assert "Food accounted for 67%" in joined
    assert "₹300.00" in joined
    assert "zero-spending" in joined


def test_narrative_insights_unchanged_period_uses_neutral_sentence() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.narrative_insights[0] == "You spent ₹0.00 this period."


# ── Daily trend chart ────────────────────────────────────────────────────


def test_daily_trend_chart_is_none_without_data() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.primary_trend_chart is None


def test_daily_trend_chart_highlights_peak_and_computes_average() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    daily_trend = TrendAnalyticsResponse(
        interval=TrendInterval.DAILY,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("60.00"),
        expense_count=3,
        data=[
            TrendDataPoint(
                period="2026-07-01",
                start_date=None,
                end_date=None,
                total=Decimal("10.00"),
                expense_count=1,
                average_expense=Decimal("10.00"),
            ),
            TrendDataPoint(
                period="2026-07-02",
                start_date=None,
                end_date=None,
                total=Decimal("50.00"),
                expense_count=1,
                average_expense=Decimal("50.00"),
            ),
        ],
    )
    data = ReportBuilder().build(_minimal_inputs(resolved, request, daily_trend=daily_trend))
    chart = data.primary_trend_chart
    assert isinstance(chart, LineChart)
    assert chart.average_value == Decimal("30.00")
    assert chart.highlight_label == "2026-07-02"
    assert chart.highlight_value == Decimal("50.00")
    assert chart.highlight is not None
    assert chart.line_path.startswith("M ")
    assert [lbl.label for lbl in chart.x_labels] == ["1", "2"]


def test_daily_trend_chart_x_labels_are_thinned_for_many_points() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 1, 20))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=1)
    daily_trend = TrendAnalyticsResponse(
        interval=TrendInterval.DAILY,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("200.00"),
        expense_count=20,
        data=[
            TrendDataPoint(
                period=f"2026-01-{day:02d}",
                start_date=None,
                end_date=None,
                total=Decimal("10.00"),
                expense_count=1,
                average_expense=Decimal("10.00"),
            )
            for day in range(1, 21)
        ],
    )
    data = ReportBuilder().build(_minimal_inputs(resolved, request, daily_trend=daily_trend))
    chart = data.primary_trend_chart
    assert isinstance(chart, LineChart)
    labels = [lbl.label for lbl in chart.x_labels]
    assert len(labels) <= 8
    assert labels[0] == "1"
    assert labels[-1] == "20"  # the last day always gets a label


def test_custom_report_daily_trend_chart_uses_date_labels() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 1, 3))
    request = ReportRequest(
        type=ReportType.CUSTOM, start_date=resolved.start_date, end_date=resolved.end_date
    )
    daily_trend = TrendAnalyticsResponse(
        interval=TrendInterval.DAILY,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("30.00"),
        expense_count=3,
        data=[
            TrendDataPoint(
                period=f"2026-01-{day:02d}",
                start_date=None,
                end_date=None,
                total=Decimal("10.00"),
                expense_count=1,
                average_expense=Decimal("10.00"),
            )
            for day in range(1, 4)
        ],
    )
    data = ReportBuilder().build(_minimal_inputs(resolved, request, daily_trend=daily_trend))
    chart = data.primary_trend_chart
    assert isinstance(chart, LineChart)
    # Custom ranges show real dates on the x-axis instead of a bare 1-based
    # position, since (unlike a monthly report) the days don't line up with
    # a single calendar month.
    assert [lbl.label for lbl in chart.x_labels] == ["1 Jan", "2 Jan", "3 Jan"]


# ── Yearly reports ───────────────────────────────────────────────────────


def _year_monthly_trend(resolved: ResolvedDateRange) -> TrendAnalyticsResponse:
    return TrendAnalyticsResponse(
        interval=TrendInterval.MONTHLY,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("300.00"),
        expense_count=3,
        data=[
            TrendDataPoint(
                period=f"2026-{month:02d}",
                start_date=None,
                end_date=None,
                total=Decimal("100.00") if month == 3 else Decimal("10.00"),
                expense_count=1,
                average_expense=Decimal("10.00"),
            )
            for month in range(1, 13)
        ],
    )


def test_average_monthly_spending_divides_total_by_month_count() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    request = ReportRequest(type=ReportType.YEARLY, year=2026)
    monthly_category = [
        MonthlyCategoryInput(period=b, breakdown=_empty_category_breakdown(b))
        for b in month_buckets(resolved)
    ]
    assert len(monthly_category) == 12
    inputs = _minimal_inputs(
        resolved,
        request,
        monthly_category=monthly_category,
        range_summary=RangeSummary(
            total=Decimal("1200.00"),
            expense_count=12,
            daily_average=Decimal("3.29"),
            average_expense=Decimal("100.00"),
            top_category=None,
            largest_expense=None,
        ),
    )
    data = ReportBuilder().build(inputs)
    assert data.summary.average_monthly_spending == Decimal("100.00")


def test_average_monthly_spending_falls_back_to_total_without_monthly_buckets() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(
        _minimal_inputs(
            resolved,
            request,
            monthly_category=[],
            range_summary=RangeSummary(
                total=Decimal("500.00"),
                expense_count=5,
                daily_average=Decimal("16.13"),
                average_expense=Decimal("100.00"),
                top_category=None,
                largest_expense=None,
            ),
        )
    )
    assert data.summary.average_monthly_spending == Decimal("500.00")


def test_yearly_report_uses_monthly_trend_for_primary_chart() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    request = ReportRequest(type=ReportType.YEARLY, year=2026)
    monthly_trend = _year_monthly_trend(resolved)
    data = ReportBuilder().build(_minimal_inputs(resolved, request, monthly_trend=monthly_trend))
    assert data.primary_trend_title == "Monthly Spending Trend"
    chart = data.primary_trend_chart
    assert isinstance(chart, VerticalBarChart)
    labels = [bar.label for bar in chart.bars]
    assert labels == [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    march_bar = chart.bars[2]
    assert march_bar.value == Decimal("100.00")
    assert march_bar.is_highest is True
    assert all(not bar.is_highest for bar in chart.bars if bar is not march_bar)


def test_non_yearly_report_uses_daily_trend_for_primary_chart() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    data = ReportBuilder().build(_minimal_inputs(resolved, request))
    assert data.primary_trend_title == "Daily Spending Trend"


def test_weekly_trend_chart_always_populated_as_line_chart() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    weekly_trend = TrendAnalyticsResponse(
        interval=TrendInterval.WEEKLY,
        start_date=resolved.start_date,
        end_date=resolved.end_date,
        total_spending=Decimal("50.00"),
        expense_count=2,
        data=[
            TrendDataPoint(
                period="2026-W27",
                start_date=None,
                end_date=None,
                total=Decimal("50.00"),
                expense_count=2,
                average_expense=Decimal("25.00"),
            )
        ],
    )
    data = ReportBuilder().build(_minimal_inputs(resolved, request, weekly_trend=weekly_trend))
    assert data.weekly_trend_chart is not None
    assert data.weekly_trend_chart.line_path.startswith("M ")
    assert data.weekly_trend is weekly_trend


def _year_heatmap_by_year(year: int) -> dict[int, CalendarHeatmapResponse]:
    return {
        year: CalendarHeatmapResponse(
            year=year,
            total_spending=Decimal("150.00"),
            expense_count=2,
            max_daily_spending=Decimal("100.00"),
            data=[
                CalendarHeatmapDay(
                    date=date(year, 2, 20),
                    month=2,
                    day=20,
                    total=Decimal("100.00"),
                    expense_count=1,
                    is_future=False,
                ),
                CalendarHeatmapDay(
                    date=date(year, 6, 30),
                    month=6,
                    day=30,
                    total=Decimal("50.00"),
                    expense_count=1,
                    is_future=False,
                ),
            ],
        )
    }


def test_yearly_report_builds_year_heatmap_matrix_not_month_grid() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    request = ReportRequest(type=ReportType.YEARLY, year=2026)
    data = ReportBuilder().build(
        _minimal_inputs(resolved, request, heatmap_by_year=_year_heatmap_by_year(2026))
    )
    assert data.heatmap is None
    assert data.year_heatmap is not None

    matrix = data.year_heatmap
    assert len(matrix.rows) == 12
    assert [row.label for row in matrix.rows] == [
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    for row in matrix.rows:
        assert len(row.days) == 31

    feb_row = matrix.rows[1]
    assert feb_row.days[27] is not None  # Feb 28 -> index 27, last day of Feb 2026
    assert feb_row.days[28] is None  # Feb 29 doesn't exist in 2026 (not a leap year)
    assert feb_row.days[29] is None
    assert feb_row.days[30] is None

    feb_20 = feb_row.days[19]
    assert feb_20 is not None
    assert feb_20.date == date(2026, 2, 20)
    assert feb_20.total == Decimal("100.00")
    assert feb_20.is_in_range is True
    assert feb_20.intensity_level == 4  # the max daily spending in the aggregate


def test_non_yearly_report_builds_month_grid_not_year_heatmap() -> None:
    resolved = ResolvedDateRange(date(2026, 7, 1), date(2026, 7, 31))
    request = ReportRequest(type=ReportType.MONTHLY, year=2026, month=7)
    heatmap_by_year = {
        2026: CalendarHeatmapResponse(
            year=2026,
            total_spending=Decimal("100.00"),
            expense_count=1,
            max_daily_spending=Decimal("100.00"),
            data=[
                CalendarHeatmapDay(
                    date=date(2026, 7, 15),
                    month=7,
                    day=15,
                    total=Decimal("100.00"),
                    expense_count=1,
                    is_future=False,
                )
            ],
        )
    }
    data = ReportBuilder().build(
        _minimal_inputs(resolved, request, heatmap_by_year=heatmap_by_year)
    )
    assert data.heatmap is not None
    assert data.year_heatmap is None


def test_yearly_report_highest_spending_day_from_year_heatmap() -> None:
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    request = ReportRequest(type=ReportType.YEARLY, year=2026)
    data = ReportBuilder().build(
        _minimal_inputs(resolved, request, heatmap_by_year=_year_heatmap_by_year(2026))
    )
    assert data.insights.highest_spending_day == date(2026, 2, 20)
    assert data.insights.highest_spending_day_total == Decimal("100.00")


def test_yearly_report_hides_expense_table_data_is_still_type_correct() -> None:
    # The Expense Table section is hidden in the *template* for yearly
    # reports (see `_expense_table.html`), not by nulling `expenses` in the
    # builder — `ReportData.expenses` stays populated regardless of type.
    resolved = ResolvedDateRange(date(2026, 1, 1), date(2026, 12, 31))
    request = ReportRequest(type=ReportType.YEARLY, year=2026)
    inputs = _minimal_inputs(
        resolved,
        request,
        expenses=[
            ExportRow(
                spent_date=date(2026, 3, 1),
                category_name="Food",
                description="Lunch",
                amount=Decimal("20.00"),
            )
        ],
    )
    data = ReportBuilder().build(inputs)
    assert len(data.expenses) == 1
    assert data.metadata.report_type is ReportType.YEARLY
