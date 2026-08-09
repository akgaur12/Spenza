"""Pydantic v2 request/response schemas for the `reports` module.

`ReportData` and its nested pieces are the sole contract between
`ReportBuilder` and the PDF templates — the builder is the only place that
constructs one, and templates only ever read from it. Wherever an existing
module's response schema already carries the right shape (`DashboardCategorySummary`,
`LargestExpenseSummary`, `MonthComparison`, `CategoryAnalyticsItem`), it's
reused directly instead of re-declared, so a report's numbers are provably
the same objects `dashboard`/`analytics` computed — never a re-derived copy.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from src.modules.analytics.schemas import (
    CategoryAnalyticsItem,
    CategoryAnalyticsResponse,
    TrendAnalyticsResponse,
)
from src.modules.dashboard.schemas import (
    DashboardCategorySummary,
    LargestExpenseSummary,
    MonthComparison,
)


class ReportType(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class ReportFormat(StrEnum):
    PDF = "pdf"


class SendReportNowResponse(BaseModel):
    sent_to: str
    filename: str


# ── Request ───────────────────────────────────────────────────────────────


class ReportRequest(BaseModel):
    """Which fields are required/forbidden per `type` is a cross-field,
    business-rule concern resolved by `date_range_resolver.resolve_date_range`
    (see its module docstring) rather than enforced here — this schema only
    captures shape (e.g. `month` fitting 1-12).
    """

    type: ReportType
    format: ReportFormat = ReportFormat.PDF
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    quarter: int | None = Field(default=None, ge=1, le=4)
    start_date: date | None = None
    end_date: date | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"type": "monthly", "year": 2026, "month": 7, "format": "pdf"},
                {"type": "quarterly", "year": 2026, "quarter": 3, "format": "pdf"},
                {"type": "yearly", "year": 2026, "format": "pdf"},
                {
                    "type": "custom",
                    "start_date": "2026-01-01",
                    "end_date": "2026-06-30",
                    "format": "pdf",
                },
            ]
        }
    }

    @model_validator(mode="after")
    def _no_cross_type_fields(self) -> "ReportRequest":
        """Reject fields that belong to a *different* report type outright
        (e.g. `quarter` on a monthly request) — a purely structural check
        that belongs on the schema. Whether the fields *this* type needs are
        actually present is a resolver-level concern (see above).
        """
        if self.type is not ReportType.CUSTOM and (
            self.start_date is not None or self.end_date is not None
        ):
            raise ValueError("start_date/end_date are only valid for type=custom.")
        if self.type is not ReportType.QUARTERLY and self.quarter is not None:
            raise ValueError("quarter is only valid for type=quarterly.")
        if self.type is ReportType.CUSTOM and (self.year is not None or self.month is not None):
            raise ValueError("year/month are not valid for type=custom.")
        if self.type is not ReportType.MONTHLY and self.month is not None:
            raise ValueError("month is only valid for type=monthly.")
        return self


# ── Report data (builder output / template input) ──────────────────────────


class ReportMetadata(BaseModel):
    report_type: ReportType
    title: str
    period_label: str
    start_date: date
    end_date: date
    generated_at: datetime
    app_name: str
    username: str
    full_name: str | None
    email: str


class ReportSummary(BaseModel):
    total_spending: Decimal
    expense_count: int
    daily_average: Decimal
    average_monthly_spending: Decimal = Field(
        description="Total spending divided by the number of months in the "
        "period — only rendered in Key Metrics for quarterly and yearly reports."
    )
    largest_expense: LargestExpenseSummary | None
    top_category: DashboardCategorySummary | None
    previous_period_total: Decimal
    previous_period_expense_count: int
    comparison: MonthComparison
    comparison_label: str = Field(
        description='"Previous Month" for monthly, "Previous Year" for yearly, '
        '"Previous Period" otherwise.'
    )


class MonthlyCategoryBucket(BaseModel):
    period_label: str
    start_date: date
    end_date: date
    total_spending: Decimal
    expense_count: int
    top_categories: list[CategoryAnalyticsItem]


class ReportHeatmapDay(BaseModel):
    date: date
    day: int
    total: Decimal
    expense_count: int
    is_in_range: bool = Field(
        description="False for padding/out-of-range days kept only to complete a calendar week."
    )
    intensity_level: int = Field(description="0-4, scaled against the heatmap's own max day.")


class HeatmapMonthGrid(BaseModel):
    label: str
    weeks: list[list[ReportHeatmapDay | None]]


class ReportHeatmap(BaseModel):
    total_spending: Decimal
    expense_count: int
    max_daily_spending: Decimal
    months: list[HeatmapMonthGrid]


class YearHeatmapRow(BaseModel):
    label: str
    days: list[ReportHeatmapDay | None] = Field(
        description="Always 31 entries (day-of-month 1-31); None past that month's last day."
    )


class YearHeatmapMatrix(BaseModel):
    """A yearly report's calendar heatmap: 12 month-rows x 31 day-columns in
    one compact grid, instead of 12 separate calendar-week grids — too many
    of those stacked vertically for a year to stay readable.
    """

    total_spending: Decimal
    expense_count: int
    max_daily_spending: Decimal
    rows: list[YearHeatmapRow] = Field(description="Always 12 entries, January first.")


class ReportExpenseRow(BaseModel):
    """Mirrors `export_formatters.ExportRow`'s rendered shape exactly — the
    task's "Exactly match export format" requirement — so the PDF report's
    table and the CSV/XLSX export always agree on what a row looks like.
    """

    date: date
    day: str
    category: str
    description: str
    amount: Decimal


class ReportInsights(BaseModel):
    highest_spending_month_label: str | None
    highest_spending_month_total: Decimal | None
    highest_spending_week_label: str | None
    highest_spending_week_total: Decimal | None
    highest_spending_weekday_label: str | None
    highest_spending_day: date | None
    highest_spending_day_total: Decimal | None


class MonthlyStatistics(BaseModel):
    """Zero-spending-day count — the one descriptive statistic over the
    period's expense list that Key Metrics still renders; no external
    service call, since it's derivable from rows the report already fetched
    for the expense table.
    """

    zero_spending_days: int


class TopExpenseItem(BaseModel):
    rank: int
    date: date
    day: str
    description: str
    category: str
    amount: Decimal


class WeekdayBar(BaseModel):
    label: str
    total: Decimal
    bar_pct: float = Field(description="0-100, scaled against this series' own largest bar.")
    is_highest: bool


class WeekdayChart(BaseModel):
    bars: list[WeekdayBar] = Field(description="Always 7 entries, Monday first.")
    highest_label: str | None


class PieSlice(BaseModel):
    label: str
    total: Decimal
    percentage: float
    color: str
    path: str = Field(description="Precomputed SVG <path> 'd' attribute for this slice.")


class DonutChart(BaseModel):
    slices: list[PieSlice]
    size: int = Field(description="SVG viewBox width/height in user units (square).")


class ChartPoint(BaseModel):
    x: float
    y: float


class ChartGridline(BaseModel):
    y: float
    label: str


class ChartXLabel(BaseModel):
    x: float
    label: str = Field(
        description="A point's x-axis label — day position, date, week position, or month."
    )


class LineChart(BaseModel):
    """A reusable smoothed-line-chart shape — the same rendering (gridlines,
    curve, average line, peak highlight) drives the daily, weekly, and
    monthly trend charts alike; only the underlying `TrendAnalyticsResponse`
    and x-axis label scheme differ per caller.
    """

    width: int
    height: int
    plot_left: float = Field(
        description="Left x-coordinate of the plot area (gridlines start here)."
    )
    baseline_y: float = Field(
        description="Y-coordinate of the plot's bottom edge (x-axis labels sit below it)."
    )
    line_path: str = Field(description="SVG <path> 'd' for the smoothed value curve.")
    area_path: str = Field(description="Same curve, closed to the baseline, for a soft fill wash.")
    gridlines: list[ChartGridline] = Field(
        description="Horizontal reference lines with axis labels."
    )
    x_labels: list[ChartXLabel] = Field(
        description="A thinned-out subset of x-axis labels, never one per point."
    )
    average_value: Decimal
    average_y: float = Field(description="Pixel y-coordinate of the average reference line.")
    highlight: ChartPoint | None = Field(
        description="Coordinates of the single highest-value point."
    )
    highlight_label: str | None
    highlight_value: Decimal | None


class VerticalBar(BaseModel):
    x: float
    y: float = Field(description="Top-left y-coordinate of the bar rectangle.")
    width: float
    height: float
    label: str
    value: Decimal
    is_highest: bool


class VerticalBarChart(BaseModel):
    """A column chart — same gridline/average-line geometry as `LineChart`,
    but rendered as discrete bars instead of a smoothed curve. Used for the
    yearly report's month-by-month primary trend, where 12 distinct columns
    read more naturally than a line.
    """

    width: int
    height: int
    plot_left: float = Field(
        description="Left x-coordinate of the plot area (gridlines start here)."
    )
    baseline_y: float = Field(
        description="Y-coordinate of the plot's bottom edge (x-axis labels sit below it)."
    )
    bars: list[VerticalBar]
    gridlines: list[ChartGridline] = Field(
        description="Horizontal reference lines with axis labels."
    )
    average_value: Decimal
    average_y: float = Field(description="Pixel y-coordinate of the average reference line.")


class ReportData(BaseModel):
    """The single object passed to the PDF templates. Built once by
    `ReportBuilder.build()` from data already collected by `ReportService` —
    see `builder.py` for what "no business logic" means for this object.
    """

    metadata: ReportMetadata
    summary: ReportSummary
    narrative_insights: list[str]
    primary_trend_title: str = Field(
        description='"Daily Spending Trend" normally; "Monthly Spending Trend" for yearly reports.'
    )
    primary_trend_chart: LineChart | VerticalBarChart | None = Field(
        description="A smoothed line normally; a vertical bar chart for yearly reports."
    )
    weekly_trend: TrendAnalyticsResponse | None = Field(
        description="Bar-chart-ready weekly totals — rendered for every type except yearly."
    )
    weekly_trend_chart: LineChart | None = Field(
        description="Line-chart-ready weekly totals — rendered only for yearly reports."
    )
    weekday_chart: WeekdayChart
    category_chart: DonutChart | None
    category_breakdown: CategoryAnalyticsResponse | None
    monthly_category: list[MonthlyCategoryBucket]
    heatmap: ReportHeatmap | None = Field(
        description="Per-month calendar-week grids — every type except yearly."
    )
    year_heatmap: YearHeatmapMatrix | None = Field(
        description="The 12x31 month-by-day matrix — yearly reports only."
    )
    heatmap_note: str | None
    top_expenses: list[TopExpenseItem]
    monthly_statistics: MonthlyStatistics
    expenses: list[ReportExpenseRow]
    insights: ReportInsights
