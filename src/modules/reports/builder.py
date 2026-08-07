"""Composes already-collected dashboard/analytics/expense data into the
single `ReportData` object the PDF templates render.

"No business logic" for this layer means: never re-derive a number that a
service already computed correctly for the exact period requested (a total,
a percentage, an average). What *does* live here is purely presentational
composition — picking the largest of several already-computed values for an
"Insights" card, laying calendar days out into a week grid, bucketing a
day's spend into one of 5 CSS intensity classes, computing SVG chart
geometry from already-fetched points — the same kind of work any
charting/rendering layer does with data it didn't compute itself. The one
exception is descriptive statistics with no service equivalent (median,
zero-spending-day count, weekday totals) — those are plain statistics over
rows already fetched for the expense table, not new business rules.
"""

import math
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from src.modules.analytics.schemas import (
    CalendarHeatmapResponse,
    CategoryAnalyticsItem,
    TrendDataPoint,
)
from src.modules.analytics.schemas import CategoryAnalyticsResponse as CategoryBreakdown
from src.modules.analytics.schemas import TrendAnalyticsResponse as TrendResponse
from src.modules.dashboard.schemas import MonthComparison, RangeSummary
from src.modules.import_export.export_formatters import (
    ExportRow,
    format_export_date,
    weekday_abbr,
)
from src.modules.reports.date_range_resolver import ResolvedDateRange
from src.modules.reports.schemas import (
    ChartGridline,
    ChartPoint,
    ChartXLabel,
    DonutChart,
    HeatmapMonthGrid,
    LineChart,
    MonthlyCategoryBucket,
    MonthlyStatistics,
    PieSlice,
    ReportData,
    ReportExpenseRow,
    ReportHeatmap,
    ReportHeatmapDay,
    ReportInsights,
    ReportMetadata,
    ReportRequest,
    ReportSummary,
    ReportType,
    TopExpenseItem,
    VerticalBar,
    VerticalBarChart,
    WeekdayBar,
    WeekdayChart,
    YearHeatmapMatrix,
    YearHeatmapRow,
)
from src.modules.users.models import User

_CENTS = Decimal("0.01")
_PERCENT = Decimal("0.01")
# WeasyPrint shapes text through Pango/Cairo with real system fonts (unlike
# ReportLab's `export_formatters.CURRENCY_FALLBACK`, which falls back to
# "INR" text because its built-in fonts can't render "₹"), so the actual
# symbol renders correctly here.
_CURRENCY_SYMBOL = "₹"

_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_TITLES: dict[ReportType, str] = {
    ReportType.MONTHLY: "Monthly Expense Report",
    ReportType.QUARTERLY: "Quarterly Expense Report",
    ReportType.YEARLY: "Yearly Expense Report",
    ReportType.CUSTOM: "Custom Expense Report",
}

_COMPARISON_LABELS: dict[ReportType, str] = {
    ReportType.MONTHLY: "Previous Month",
    ReportType.YEARLY: "Previous Year",
}

# A donut/pie chart stops being legible past ~6 segments — every slice
# beyond the top 5 folds into a single "Other" wedge instead of a 10th hue.
_DONUT_MAX_SLICES = 5
# A fixed-order, colorblind-safe categorical sequence (blue/orange/aqua/
# yellow/magenta) — assigned by rank, never re-picked per request.
_DONUT_PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4")
_DONUT_OTHER_COLOR = "#9ca3af"
_DONUT_SIZE = 120

_TOP_EXPENSES_LIMIT = 10
# The Category Breakdown table shows at most this many rows — the donut
# chart above it has its own, stricter 5-slice cap for legibility, but a
# plain table can comfortably list more rows.
_CATEGORY_BREAKDOWN_LIMIT = 10

# Pixel-space geometry for the inline SVG daily trend line chart.
_CHART_WIDTH = 660
_CHART_HEIGHT = 160
_CHART_PADDING_TOP = 14
_CHART_PADDING_RIGHT = 12
_CHART_PADDING_BOTTOM = 24
_CHART_PADDING_LEFT = 56
_CHART_GRIDLINE_COUNT = 4
# Caps how many day-position labels the x-axis shows — never one per point,
# which would collide for anything past ~15 days.
_CHART_MAX_X_LABELS = 8
# A vertical bar chart's bar width as a fraction of its evenly-divided
# slot — leaves a visible gap between adjacent columns.
_BAR_WIDTH_FRACTION = 0.55


def _money(value: Decimal) -> str:
    return f"{_CURRENCY_SYMBOL}{value:,.2f}"


@dataclass(frozen=True, slots=True)
class MonthlyCategoryInput:
    period: ResolvedDateRange
    breakdown: CategoryBreakdown


@dataclass(frozen=True, slots=True)
class ReportInputs:
    """Everything `ReportService` collected from other services/repositories
    for one report generation, handed to `ReportBuilder.build()` as-is.
    """

    user: User
    request: ReportRequest
    resolved: ResolvedDateRange
    generated_at: datetime
    range_summary: RangeSummary
    previous_summary: RangeSummary
    category_breakdown: CategoryBreakdown
    daily_trend: TrendResponse
    weekly_trend: TrendResponse
    monthly_trend: TrendResponse
    monthly_category: list[MonthlyCategoryInput]
    heatmap_by_year: dict[int, CalendarHeatmapResponse]
    heatmap_note: str | None
    expenses: list[ExportRow]
    top_categories_per_month: int = 5


def _period_label(request: ReportRequest, resolved: ResolvedDateRange) -> str:
    if request.type is ReportType.MONTHLY:
        return f"{_MONTH_NAMES[resolved.start_date.month - 1]} {resolved.start_date.year}"
    if request.type is ReportType.QUARTERLY:
        quarter = (resolved.start_date.month - 1) // 3 + 1
        return f"Q{quarter} {resolved.start_date.year}"
    if request.type is ReportType.YEARLY:
        return str(resolved.start_date.year)
    return f"{format_export_date(resolved.start_date)} to {format_export_date(resolved.end_date)}"


def _compare_periods(current_total: Decimal, previous_total: Decimal) -> MonthComparison:
    """Generalizes `dashboard.service._compare_months` to any two
    equal-length periods — reuses its exact difference/percentage/trend
    formula (see there for the zero-base rationale) rather than defining a
    second one.
    """
    difference = (current_total - previous_total).quantize(_CENTS, rounding=ROUND_HALF_UP)
    trend: Literal["up", "down", "same"]
    if difference > 0:
        trend = "up"
    elif difference < 0:
        trend = "down"
    else:
        trend = "same"

    percentage_change: float | None
    if previous_total == 0:
        percentage_change = 0.0 if difference == 0 else None
    else:
        percentage_change = float(
            (difference / previous_total * 100).quantize(_PERCENT, rounding=ROUND_HALF_UP)
        )
    return MonthComparison(difference=difference, percentage_change=percentage_change, trend=trend)


def _intensity_level(total: Decimal, max_total: Decimal) -> int:
    if max_total <= 0 or total <= 0:
        return 0
    ratio = float(total / max_total)
    return min(4, 1 + int(ratio * 3.999))


def _month_grid(
    year: int,
    month: int,
    days_by_date: dict[date, tuple[Decimal, int]],
    in_range: tuple[date, date],
    max_total: Decimal,
) -> HeatmapMonthGrid:
    leading_pad, days_in_month = monthrange(year, month)
    cells: list[ReportHeatmapDay | None] = [None] * leading_pad
    for day_number in range(1, days_in_month + 1):
        day_date = date(year, month, day_number)
        total, count = days_by_date.get(day_date, (Decimal("0.00"), 0))
        cells.append(
            ReportHeatmapDay(
                date=day_date,
                day=day_number,
                total=total,
                expense_count=count,
                is_in_range=in_range[0] <= day_date <= in_range[1],
                intensity_level=_intensity_level(total, max_total),
            )
        )
    while len(cells) % 7:
        cells.append(None)
    weeks = [cells[i : i + 7] for i in range(0, len(cells), 7)]
    return HeatmapMonthGrid(label=f"{_MONTH_NAMES[month - 1][:3]} {year}", weeks=weeks)


def _year_heatmap_row(
    year: int, month: int, days_by_date: dict[date, tuple[Decimal, int]], max_total: Decimal
) -> YearHeatmapRow:
    _, days_in_month = monthrange(year, month)
    cells: list[ReportHeatmapDay | None] = []
    for day_number in range(1, 32):
        if day_number > days_in_month:
            cells.append(None)
            continue
        day_date = date(year, month, day_number)
        total, count = days_by_date.get(day_date, (Decimal("0.00"), 0))
        cells.append(
            ReportHeatmapDay(
                date=day_date,
                day=day_number,
                total=total,
                expense_count=count,
                is_in_range=True,  # a yearly report's own year is fully in-range by construction
                intensity_level=_intensity_level(total, max_total),
            )
        )
    return YearHeatmapRow(label=_MONTH_NAMES[month - 1][:3], days=cells)


@dataclass(frozen=True, slots=True)
class _HeatmapAggregate:
    """The raw per-day totals shared by both heatmap presentations — month-
    grid (`_build_month_grid_heatmap`) and year-matrix (`_build_year_heatmap`)
    render the exact same underlying data, just laid out differently.
    """

    days_by_date: dict[date, tuple[Decimal, int]]
    total_spending: Decimal
    expense_count: int
    max_daily_spending: Decimal


def _build_weekday_chart(expenses: list[ExportRow]) -> WeekdayChart:
    totals = [Decimal("0.00")] * 7
    for row in expenses:
        totals[row.spent_date.weekday()] += row.amount

    max_total = max(totals)
    highest_index = max(range(7), key=lambda i: totals[i]) if max_total > 0 else None

    bars = [
        WeekdayBar(
            label=_WEEKDAY_ABBR[i],
            total=totals[i],
            bar_pct=float(totals[i] / max_total * 100) if max_total > 0 else 0.0,
            is_highest=(i == highest_index),
        )
        for i in range(7)
    ]
    highest_label = _WEEKDAY_NAMES[highest_index] if highest_index is not None else None
    return WeekdayChart(bars=bars, highest_label=highest_label)


def _polar_point(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    angle_rad = math.radians(angle_deg - 90)
    return cx + r * math.cos(angle_rad), cy + r * math.sin(angle_rad)


def _donut_slice_path(
    cx: float, cy: float, r_outer: float, r_inner: float, start_angle: float, end_angle: float
) -> str:
    end_angle = min(end_angle, start_angle + 359.99)  # a true 360deg arc is degenerate in SVG
    large_arc = 1 if (end_angle - start_angle) > 180 else 0
    x1, y1 = _polar_point(cx, cy, r_outer, start_angle)
    x2, y2 = _polar_point(cx, cy, r_outer, end_angle)
    x3, y3 = _polar_point(cx, cy, r_inner, end_angle)
    x4, y4 = _polar_point(cx, cy, r_inner, start_angle)
    return (
        f"M {x1:.2f} {y1:.2f} A {r_outer} {r_outer} 0 {large_arc} 1 {x2:.2f} {y2:.2f} "
        f"L {x3:.2f} {y3:.2f} A {r_inner} {r_inner} 0 {large_arc} 0 {x4:.2f} {y4:.2f} Z"
    )


def _build_category_chart(categories: list[CategoryAnalyticsItem]) -> DonutChart | None:
    total = sum((c.total for c in categories), Decimal("0.00"))
    if not categories or total <= 0:
        return None

    top = categories[:_DONUT_MAX_SLICES]
    other_total = sum((c.total for c in categories[_DONUT_MAX_SLICES:]), Decimal("0.00"))
    entries: list[tuple[str, Decimal, str]] = [
        (c.name, c.total, _DONUT_PALETTE[i]) for i, c in enumerate(top)
    ]
    if other_total > 0:
        entries.append(("Other", other_total, _DONUT_OTHER_COLOR))

    cx = cy = _DONUT_SIZE / 2
    r_outer, r_inner = _DONUT_SIZE / 2 - 5, _DONUT_SIZE / 4
    cursor = 0.0
    slices: list[PieSlice] = []
    for name, value, color in entries:
        sweep = float(value / total) * 360.0
        slices.append(
            PieSlice(
                label=name,
                total=value,
                percentage=float(value / total * 100),
                color=color,
                path=_donut_slice_path(cx, cy, r_outer, r_inner, cursor, cursor + sweep),
            )
        )
        cursor += sweep
    return DonutChart(slices=slices, size=_DONUT_SIZE)


def _nice_axis_step(rough_step: float) -> float:
    """Round a raw "value per gridline" up to a clean 1/2/5x10^n step, the
    same convention `marks-and-anatomy` prescribes for axis ticks (0 / 1,000
    / 2,000, never an arbitrary fraction).
    """
    if rough_step <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(rough_step))
    residual = rough_step / magnitude
    if residual <= 1:
        nice = 1.0
    elif residual <= 2:
        nice = 2.0
    elif residual <= 5:
        nice = 5.0
    else:
        nice = 10.0
    return float(nice * magnitude)


def _axis_label(value: float) -> str:
    return f"{_CURRENCY_SYMBOL}{value:,.0f}"


def _smooth_line_path(coords: list[tuple[float, float]]) -> str:
    """A Catmull-Rom-through-cubic-Bezier curve — a proper smoothed line
    rather than jagged point-to-point segments, which is what a daily
    spending series (naturally noisy day to day) needs to read as a trend.
    Falls back to straight segments for fewer than 3 points, where a curve
    isn't meaningfully different anyway.

    Each segment's control points are clamped to that segment's own two
    endpoints' y-range. Unclamped Catmull-Rom can overshoot past the actual
    data (e.g. a sharp spike next to a flat run of zeros swings the curve
    below the zero baseline) — a cubic Bezier is guaranteed to stay within
    the convex hull of its 4 control points, so clamping the 2 control
    points into [min(p1.y, p2.y), max(p1.y, p2.y)] guarantees the curve
    itself never leaves that range either.
    """
    if len(coords) < 3:
        return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)

    padded = [coords[0], *coords, coords[-1]]
    parts = [f"M {coords[0][0]:.1f} {coords[0][1]:.1f}"]
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        c1x, c1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
        c2x, c2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
        seg_min_y, seg_max_y = min(p1[1], p2[1]), max(p1[1], p2[1])
        c1y = min(max(c1y, seg_min_y), seg_max_y)
        c2y = min(max(c2y, seg_min_y), seg_max_y)
        parts.append(f"C {c1x:.1f} {c1y:.1f} {c2x:.1f} {c2y:.1f} {p2[0]:.1f} {p2[1]:.1f}")
    return " ".join(parts)


def _position_label(index: int, _point: TrendDataPoint) -> str:
    """1-based sequence number — day N or week N, whichever series this is."""
    return str(index + 1)


def _month_label(_index: int, point: TrendDataPoint) -> str:
    """`point.period` for a MONTHLY-interval point is "YYYY-MM" — a 3-letter
    month abbreviation is far more legible on a 12-point axis than a bare
    sequence number.
    """
    month_number = int(point.period.split("-")[1])
    return _MONTH_NAMES[month_number - 1][:3]


def _date_label(_index: int, point: TrendDataPoint) -> str:
    """`point.period` for a DAILY-interval point is "YYYY-MM-DD". A custom
    range's days don't line up with a single calendar month the way a
    monthly report's do (where day-of-month and 1-based position are the
    same number), so the actual date reads far better than a bare position.
    """
    _year, month, day = point.period.split("-")
    return f"{int(day)} {_MONTH_NAMES[int(month) - 1][:3]}"


def _chart_axis_max(values: list[Decimal]) -> tuple[float, float]:
    """Shared "nice" y-axis scale for every SVG trend chart: `(axis_max,
    step)`, where `axis_max` is always an exact multiple of `step` and at
    least as large as the series' own peak.
    """
    raw_max = float(max(values))
    step = _nice_axis_step(raw_max / _CHART_GRIDLINE_COUNT) if raw_max > 0 else 1.0
    axis_max = step * _CHART_GRIDLINE_COUNT
    while axis_max < raw_max:  # rounding can occasionally undershoot
        axis_max += step
    return axis_max, step


def _build_line_chart(
    trend: TrendResponse,
    label_for: Callable[[int, TrendDataPoint], str],
    max_x_labels: int = _CHART_MAX_X_LABELS,
) -> LineChart | None:
    """Builds the shared smoothed-line-chart shape — used for the daily and
    weekly trend sections (see `LineChart`'s docstring). `label_for` picks
    the x-axis label scheme; `max_x_labels` lets a small, inherently-
    meaningful series show every label instead of thinning like a 30+ point
    daily/weekly series would need to.
    """
    points = trend.data
    if not points:
        return None

    values = [p.total for p in points]
    axis_max, step = _chart_axis_max(values)

    count = len(points)
    plot_w = _CHART_WIDTH - _CHART_PADDING_LEFT - _CHART_PADDING_RIGHT
    plot_h = _CHART_HEIGHT - _CHART_PADDING_TOP - _CHART_PADDING_BOTTOM
    baseline_y = _CHART_PADDING_TOP + plot_h

    def _value_y(value: float) -> float:
        return baseline_y - (value / axis_max) * plot_h

    def _xy(index: int, value: Decimal) -> tuple[float, float]:
        x = _CHART_PADDING_LEFT + (plot_w * index / (count - 1) if count > 1 else plot_w / 2)
        return x, _value_y(float(value))

    coords = [_xy(i, p.total) for i, p in enumerate(points)]
    line_path = _smooth_line_path(coords)
    area_path = (
        f"{line_path} L {coords[-1][0]:.1f} {baseline_y:.1f} "
        f"L {coords[0][0]:.1f} {baseline_y:.1f} Z"
    )

    gridlines = [
        ChartGridline(y=_value_y(step * i), label=_axis_label(step * i))
        for i in range(_CHART_GRIDLINE_COUNT + 1)
    ]

    # A thinned, evenly-spaced subset of labels (never one per point — that
    # collides for anything past ~15 points) — always including the last
    # point so the axis doesn't stop short of the data.
    label_step = max(1, math.ceil(count / max_x_labels))
    label_indices = list(range(0, count, label_step))
    if label_indices[-1] != count - 1:
        label_indices.append(count - 1)
    x_labels = [ChartXLabel(x=coords[i][0], label=label_for(i, points[i])) for i in label_indices]

    average = (sum(values, Decimal("0.00")) / count).quantize(_CENTS, rounding=ROUND_HALF_UP)
    average_y = _value_y(float(average))

    peak_index = max(range(count), key=lambda i: values[i])
    peak_x, peak_y = coords[peak_index]

    return LineChart(
        width=_CHART_WIDTH,
        height=_CHART_HEIGHT,
        plot_left=_CHART_PADDING_LEFT,
        baseline_y=baseline_y,
        line_path=line_path,
        area_path=area_path,
        gridlines=gridlines,
        x_labels=x_labels,
        average_value=average,
        average_y=average_y,
        highlight=ChartPoint(x=peak_x, y=peak_y),
        highlight_label=points[peak_index].period,
        highlight_value=points[peak_index].total,
    )


def _build_vertical_bar_chart(
    trend: TrendResponse, label_for: Callable[[int, TrendDataPoint], str]
) -> VerticalBarChart | None:
    """A column-per-point chart on the same gridline/average-line geometry
    as `_build_line_chart` — used for the yearly report's month-by-month
    primary trend, where 12 discrete totals read better as bars than as a
    smoothed curve.
    """
    points = trend.data
    if not points:
        return None

    values = [p.total for p in points]
    axis_max, step = _chart_axis_max(values)

    count = len(points)
    plot_w = _CHART_WIDTH - _CHART_PADDING_LEFT - _CHART_PADDING_RIGHT
    plot_h = _CHART_HEIGHT - _CHART_PADDING_TOP - _CHART_PADDING_BOTTOM
    baseline_y = _CHART_PADDING_TOP + plot_h

    def _value_y(value: float) -> float:
        return baseline_y - (value / axis_max) * plot_h

    slot_w = plot_w / count
    bar_w = slot_w * _BAR_WIDTH_FRACTION
    highest_index = max(range(count), key=lambda i: values[i]) if float(max(values)) > 0 else None

    bars = [
        VerticalBar(
            x=_CHART_PADDING_LEFT + slot_w * i + (slot_w - bar_w) / 2,
            y=_value_y(float(point.total)),
            width=bar_w,
            height=baseline_y - _value_y(float(point.total)),
            label=label_for(i, point),
            value=point.total,
            is_highest=(i == highest_index),
        )
        for i, point in enumerate(points)
    ]

    gridlines = [
        ChartGridline(y=_value_y(step * i), label=_axis_label(step * i))
        for i in range(_CHART_GRIDLINE_COUNT + 1)
    ]

    average = (sum(values, Decimal("0.00")) / count).quantize(_CENTS, rounding=ROUND_HALF_UP)
    average_y = _value_y(float(average))

    return VerticalBarChart(
        width=_CHART_WIDTH,
        height=_CHART_HEIGHT,
        plot_left=_CHART_PADDING_LEFT,
        baseline_y=baseline_y,
        bars=bars,
        gridlines=gridlines,
        average_value=average,
        average_y=average_y,
    )


def _build_top_expenses(expenses: list[ExportRow]) -> list[TopExpenseItem]:
    ranked = sorted(expenses, key=lambda row: row.amount, reverse=True)[:_TOP_EXPENSES_LIMIT]
    return [
        TopExpenseItem(
            rank=index + 1,
            date=row.spent_date,
            day=weekday_abbr(row.spent_date),
            description=row.description,
            category=row.category_name,
            amount=row.amount,
        )
        for index, row in enumerate(ranked)
    ]


def _build_monthly_statistics(expenses: list[ExportRow], span_days: int) -> MonthlyStatistics:
    spending_days = len({row.spent_date for row in expenses})
    return MonthlyStatistics(zero_spending_days=max(span_days - spending_days, 0))


def _build_narrative_insights(
    summary: ReportSummary,
    insights: ReportInsights,
    stats: MonthlyStatistics,
    monthly_category: list[MonthlyCategoryBucket],
) -> list[str]:
    """Templated sentences over already-computed numbers — pure statistics,
    no AI, matching the task's "No AI. Pure statistics." requirement.
    """
    lines: list[str] = []
    comparison = summary.comparison
    if comparison.percentage_change is not None and comparison.trend != "same":
        direction = "more" if comparison.trend == "up" else "less"
        lines.append(
            f"You spent {_money(summary.total_spending)}, which is "
            f"{abs(comparison.percentage_change):.1f}% {direction} than the "
            f"{summary.comparison_label.lower()}."
        )
    else:
        lines.append(f"You spent {_money(summary.total_spending)} this period.")

    if summary.top_category is not None:
        lines.append(
            f"{summary.top_category.name} accounted for "
            f"{summary.top_category.percentage:.0f}% of your spending."
        )
    if summary.largest_expense is not None:
        lines.append(f"Your largest expense was {_money(summary.largest_expense.amount)}.")
    if insights.highest_spending_weekday_label:
        lines.append(
            f"{insights.highest_spending_weekday_label} was your highest spending weekday."
        )
    if len(monthly_category) > 1 and insights.highest_spending_month_label:
        lines.append(f"{insights.highest_spending_month_label} was your highest spending month.")
    if stats.zero_spending_days > 0:
        day_word = "day" if stats.zero_spending_days == 1 else "days"
        lines.append(f"You had {stats.zero_spending_days} zero-spending {day_word} this period.")
    return lines


class ReportBuilder:
    def build(self, inputs: ReportInputs) -> ReportData:
        is_yearly = inputs.request.type is ReportType.YEARLY

        metadata = self._build_metadata(inputs)
        summary = self._build_summary(inputs)
        monthly_category = self._build_monthly_category(inputs)
        expenses = self._build_expenses(inputs)
        weekday_chart = _build_weekday_chart(inputs.expenses)
        category_chart = _build_category_chart(inputs.category_breakdown.categories)
        top_expenses = _build_top_expenses(inputs.expenses)
        monthly_statistics = _build_monthly_statistics(inputs.expenses, inputs.resolved.span_days)

        # A year's worth of daily points doesn't read well as "the daily
        # trend" — a yearly report leads with month-by-month totals instead,
        # and its own "weekly" section becomes a 52-point line rather than
        # 52 bar rows. Every other type keeps daily-line + weekly-bars.
        primary_trend_chart: LineChart | VerticalBarChart | None
        if is_yearly:
            primary_trend_title = "Monthly Spending Trend"
            primary_trend_chart = _build_vertical_bar_chart(inputs.monthly_trend, _month_label)
        else:
            primary_trend_title = "Daily Spending Trend"
            # A custom range's days don't share a single calendar month the
            # way a monthly report's do, so its x-axis shows real dates
            # rather than a bare day-of-range position.
            daily_label = (
                _date_label if inputs.request.type is ReportType.CUSTOM else _position_label
            )
            primary_trend_chart = _build_line_chart(inputs.daily_trend, daily_label)
        weekly_trend_chart = _build_line_chart(inputs.weekly_trend, _position_label)

        heatmap_aggregate = self._collect_heatmap_aggregate(inputs)
        heatmap: ReportHeatmap | None = None
        year_heatmap: YearHeatmapMatrix | None = None
        in_range_days: list[ReportHeatmapDay] = []
        if heatmap_aggregate is not None:
            if is_yearly:
                year_heatmap = self._build_year_heatmap(
                    heatmap_aggregate, inputs.resolved.start_date.year
                )
                in_range_days = [day for row in year_heatmap.rows for day in row.days if day]
            else:
                heatmap = self._build_month_grid_heatmap(heatmap_aggregate, inputs.resolved)
                in_range_days = [
                    day
                    for grid in heatmap.months
                    for week in grid.weeks
                    for day in week
                    if day is not None and day.is_in_range
                ]

        insights = self._build_insights(inputs, monthly_category, in_range_days, weekday_chart)
        narrative_insights = _build_narrative_insights(
            summary, insights, monthly_statistics, monthly_category
        )
        # Insights/donut above both read from `inputs.category_breakdown`
        # directly (their own selection/capping rules) — only the rendered
        # table itself is capped here, so a display limit never quietly
        # changes "most expensive category" or the chart.
        category_breakdown = inputs.category_breakdown.model_copy(
            update={"categories": inputs.category_breakdown.categories[:_CATEGORY_BREAKDOWN_LIMIT]}
        )

        return ReportData(
            metadata=metadata,
            summary=summary,
            narrative_insights=narrative_insights,
            primary_trend_title=primary_trend_title,
            primary_trend_chart=primary_trend_chart,
            weekly_trend=inputs.weekly_trend,
            weekly_trend_chart=weekly_trend_chart,
            weekday_chart=weekday_chart,
            category_chart=category_chart,
            category_breakdown=category_breakdown,
            monthly_category=monthly_category,
            heatmap=heatmap,
            year_heatmap=year_heatmap,
            heatmap_note=None if heatmap_aggregate is not None else inputs.heatmap_note,
            top_expenses=top_expenses,
            monthly_statistics=monthly_statistics,
            expenses=expenses,
            insights=insights,
        )

    def _build_metadata(self, inputs: ReportInputs) -> ReportMetadata:
        return ReportMetadata(
            report_type=inputs.request.type,
            title=_TITLES[inputs.request.type],
            period_label=_period_label(inputs.request, inputs.resolved),
            start_date=inputs.resolved.start_date,
            end_date=inputs.resolved.end_date,
            generated_at=inputs.generated_at,
            app_name="Spenza",
            username=inputs.user.username,
            full_name=inputs.user.full_name,
            email=inputs.user.email,
        )

    def _build_summary(self, inputs: ReportInputs) -> ReportSummary:
        current = inputs.range_summary
        previous = inputs.previous_summary
        month_count = len(inputs.monthly_category) or 1
        average_monthly_spending = (current.total / month_count).quantize(
            _CENTS, rounding=ROUND_HALF_UP
        )
        return ReportSummary(
            total_spending=current.total,
            expense_count=current.expense_count,
            daily_average=current.daily_average,
            average_monthly_spending=average_monthly_spending,
            largest_expense=current.largest_expense,
            top_category=current.top_category,
            previous_period_total=previous.total,
            previous_period_expense_count=previous.expense_count,
            comparison=_compare_periods(current.total, previous.total),
            comparison_label=_COMPARISON_LABELS.get(inputs.request.type, "Previous Period"),
        )

    def _build_monthly_category(self, inputs: ReportInputs) -> list[MonthlyCategoryBucket]:
        return [
            MonthlyCategoryBucket(
                period_label=f"{_MONTH_NAMES[item.period.start_date.month - 1][:3]} "
                f"{item.period.start_date.year}",
                start_date=item.period.start_date,
                end_date=item.period.end_date,
                total_spending=item.breakdown.total_spending,
                expense_count=item.breakdown.expense_count,
                top_categories=item.breakdown.categories[: inputs.top_categories_per_month],
            )
            for item in inputs.monthly_category
        ]

    def _collect_heatmap_aggregate(self, inputs: ReportInputs) -> _HeatmapAggregate | None:
        if not inputs.heatmap_by_year:
            return None

        days_by_date: dict[date, tuple[Decimal, int]] = {}
        total_spending = Decimal("0.00")
        expense_count = 0
        max_daily_spending = Decimal("0.00")
        for response in inputs.heatmap_by_year.values():
            for day in response.data:
                if not (inputs.resolved.start_date <= day.date <= inputs.resolved.end_date):
                    continue
                days_by_date[day.date] = (day.total, day.expense_count)
                total_spending += day.total
                expense_count += day.expense_count
                max_daily_spending = max(max_daily_spending, day.total)

        return _HeatmapAggregate(
            days_by_date=days_by_date,
            total_spending=total_spending,
            expense_count=expense_count,
            max_daily_spending=max_daily_spending,
        )

    def _build_month_grid_heatmap(
        self, aggregate: _HeatmapAggregate, resolved: ResolvedDateRange
    ) -> ReportHeatmap:
        months: list[HeatmapMonthGrid] = []
        start_date, end_date = resolved.start_date, resolved.end_date
        cursor_year, cursor_month = start_date.year, start_date.month
        end_year, end_month = end_date.year, end_date.month
        while (cursor_year, cursor_month) <= (end_year, end_month):
            months.append(
                _month_grid(
                    cursor_year,
                    cursor_month,
                    aggregate.days_by_date,
                    (start_date, end_date),
                    aggregate.max_daily_spending,
                )
            )
            cursor_year, cursor_month = (
                (cursor_year + 1, 1) if cursor_month == 12 else (cursor_year, cursor_month + 1)
            )

        return ReportHeatmap(
            total_spending=aggregate.total_spending,
            expense_count=aggregate.expense_count,
            max_daily_spending=aggregate.max_daily_spending,
            months=months,
        )

    def _build_year_heatmap(self, aggregate: _HeatmapAggregate, year: int) -> YearHeatmapMatrix:
        rows = [
            _year_heatmap_row(year, month, aggregate.days_by_date, aggregate.max_daily_spending)
            for month in range(1, 13)
        ]
        return YearHeatmapMatrix(
            total_spending=aggregate.total_spending,
            expense_count=aggregate.expense_count,
            max_daily_spending=aggregate.max_daily_spending,
            rows=rows,
        )

    def _build_expenses(self, inputs: ReportInputs) -> list[ReportExpenseRow]:
        return [
            ReportExpenseRow(
                date=row.spent_date,
                day=weekday_abbr(row.spent_date),
                category=row.category_name,
                description=row.description,
                amount=row.amount,
            )
            for row in inputs.expenses
        ]

    def _build_insights(
        self,
        inputs: ReportInputs,
        monthly_category: list[MonthlyCategoryBucket],
        in_range_days: list[ReportHeatmapDay],
        weekday_chart: WeekdayChart,
    ) -> ReportInsights:
        highest_month = max(monthly_category, key=lambda b: b.total_spending, default=None)
        highest_week_point = max(inputs.weekly_trend.data, key=lambda p: p.total, default=None)
        highest_day = max(in_range_days, key=lambda d: d.total, default=None)

        return ReportInsights(
            highest_spending_month_label=highest_month.period_label if highest_month else None,
            highest_spending_month_total=highest_month.total_spending if highest_month else None,
            highest_spending_week_label=highest_week_point.period if highest_week_point else None,
            highest_spending_week_total=highest_week_point.total if highest_week_point else None,
            highest_spending_weekday_label=weekday_chart.highest_label,
            highest_spending_day=highest_day.date if highest_day else None,
            highest_spending_day_total=highest_day.total if highest_day else None,
        )
