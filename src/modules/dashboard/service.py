"""Business logic for the `dashboard` module.

All period boundaries ("today", "this week", ...) are computed as
timezone-aware datetimes in the app's single configured zone (`APP_TIMEZONE`
— there is no per-user timezone preference yet), then converted to UTC
before querying, since `Expense.spent_at` is stored and compared as
UTC-aware `TIMESTAMPTZ`. Boundaries are half-open `[start, end)` ranges so
they can be compared directly without `23:59:59.999999` fudging.

Calendar-boundary math (start of day/week/month/year, ...) lives in
`src.core.periods`, shared with the `analytics` module so both features
bucket time identically.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.periods import (
    days_elapsed,
    months_elapsed_in_year,
    start_of_day,
    start_of_month,
    start_of_previous_month,
    start_of_week,
    start_of_year,
)
from src.core.timezone import APP_TIMEZONE
from src.modules.categories.models import Category
from src.modules.dashboard.repository import DashboardRepository
from src.modules.dashboard.schemas import (
    DashboardCategorySummary,
    DashboardSummaryResponse,
    LargestExpenseCategory,
    LargestExpenseSummary,
    MonthComparison,
    MonthSummary,
    PreviousMonthSummary,
    RangeSummary,
    TodaySummary,
    WeekSummary,
    YearSummary,
)
from src.modules.expenses.models import Expense
from src.modules.users.models import User

_CENTS = Decimal("0.01")
_PERCENT = Decimal("0.01")


@dataclass(frozen=True)
class _Boundaries:
    now_utc: datetime
    today_start: datetime
    today_end: datetime
    week_start: datetime
    month_start: datetime
    year_start: datetime
    previous_month_start: datetime
    days_elapsed_week: int
    days_elapsed_month: int
    months_elapsed_year: int


def _compute_boundaries(now_local: datetime) -> _Boundaries:
    today_start_local = start_of_day(now_local)
    week_start_local = start_of_week(now_local)
    month_start_local = start_of_month(now_local)
    year_start_local = start_of_year(now_local)
    previous_month_start_local = start_of_previous_month(month_start_local)

    return _Boundaries(
        now_utc=now_local.astimezone(UTC),
        today_start=today_start_local.astimezone(UTC),
        today_end=(today_start_local + timedelta(days=1)).astimezone(UTC),
        week_start=week_start_local.astimezone(UTC),
        month_start=month_start_local.astimezone(UTC),
        year_start=year_start_local.astimezone(UTC),
        previous_month_start=previous_month_start_local.astimezone(UTC),
        days_elapsed_week=days_elapsed(week_start_local, today_start_local),
        days_elapsed_month=days_elapsed(month_start_local, today_start_local),
        months_elapsed_year=months_elapsed_in_year(now_local),
    )


def _divide(total: Decimal, denominator: int) -> Decimal:
    return (total / denominator).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _average_expense(total: Decimal, count: int) -> Decimal:
    if count == 0:
        return Decimal("0.00")
    return _divide(total, count)


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._dashboard = DashboardRepository(session)

    async def get_summary(self, user: User) -> DashboardSummaryResponse:
        b = _compute_boundaries(datetime.now(APP_TIMEZONE))

        today_total, today_count = await self._dashboard.get_period_summary(
            user.id, b.today_start, b.today_end
        )
        week_total, week_count = await self._dashboard.get_period_summary(
            user.id, b.week_start, b.now_utc
        )
        month_total, month_count = await self._dashboard.get_period_summary(
            user.id, b.month_start, b.now_utc
        )
        year_total, year_count = await self._dashboard.get_period_summary(
            user.id, b.year_start, b.now_utc
        )
        previous_month_total, previous_month_count = await self._dashboard.get_period_summary(
            user.id, b.previous_month_start, b.month_start
        )
        top_category_row = await self._dashboard.get_top_category(user.id, b.month_start, b.now_utc)
        largest_expense = await self._dashboard.get_largest_expense(
            user.id, b.month_start, b.now_utc
        )

        return DashboardSummaryResponse(
            today=TodaySummary(total=today_total, expense_count=today_count),
            this_week=WeekSummary(
                total=week_total,
                expense_count=week_count,
                daily_average=_divide(week_total, b.days_elapsed_week),
            ),
            this_month=MonthSummary(
                total=month_total,
                expense_count=month_count,
                daily_average=_divide(month_total, b.days_elapsed_month),
                average_expense=_average_expense(month_total, month_count),
            ),
            this_year=YearSummary(
                total=year_total,
                expense_count=year_count,
                monthly_average=_divide(year_total, b.months_elapsed_year),
                average_expense=_average_expense(year_total, year_count),
            ),
            previous_month=PreviousMonthSummary(
                total=previous_month_total, expense_count=previous_month_count
            ),
            month_comparison=_compare_months(month_total, previous_month_total),
            top_category=_to_top_category(top_category_row, month_total),
            largest_expense=_to_largest_expense(largest_expense),
        )

    async def get_range_summary(
        self, user: User, start_utc: datetime, end_utc: datetime, span_days: int
    ) -> RangeSummary:
        """The same metrics as `this_month`/`this_year` in `get_summary()`,
        generalized to an arbitrary `[start_utc, end_utc)` range — e.g. a
        past calendar month/quarter/year a report was asked to cover, which
        `get_summary()` can't serve since it's anchored to "now".
        `span_days` is the caller's own day count for the range (not
        recomputed here, since "half-open UTC range" and "calendar day
        count" are two different things the caller already knows).
        """
        total, count = await self._dashboard.get_period_summary(user.id, start_utc, end_utc)
        top_category_row = await self._dashboard.get_top_category(user.id, start_utc, end_utc)
        largest_expense = await self._dashboard.get_largest_expense(user.id, start_utc, end_utc)

        return RangeSummary(
            total=total,
            expense_count=count,
            daily_average=_divide(total, span_days) if span_days > 0 else Decimal("0.00"),
            average_expense=_average_expense(total, count),
            top_category=_to_top_category(top_category_row, total),
            largest_expense=_to_largest_expense(largest_expense),
        )


def _compare_months(month_total: Decimal, previous_month_total: Decimal) -> MonthComparison:
    difference = (month_total - previous_month_total).quantize(_CENTS, rounding=ROUND_HALF_UP)

    trend: Literal["up", "down", "same"]
    if difference > 0:
        trend = "up"
    elif difference < 0:
        trend = "down"
    else:
        trend = "same"

    percentage_change: float | None
    if previous_month_total == 0:
        # Percentage growth from a zero base is undefined; `difference` can
        # only be >= 0 here since expense amounts are always positive.
        percentage_change = 0.0 if difference == 0 else None
    else:
        percentage_change = float(
            (difference / previous_month_total * 100).quantize(_PERCENT, rounding=ROUND_HALF_UP)
        )

    return MonthComparison(difference=difference, percentage_change=percentage_change, trend=trend)


def _to_top_category(
    row: tuple[Category, Decimal, int] | None, month_total: Decimal
) -> DashboardCategorySummary | None:
    if row is None:
        return None
    category, category_total, category_count = row
    percentage = float(
        (category_total / month_total * 100).quantize(_PERCENT, rounding=ROUND_HALF_UP)
    )
    return DashboardCategorySummary(
        category_id=category.id,
        name=category.name,
        icon=category.icon,
        total=category_total,
        expense_count=category_count,
        percentage=percentage,
    )


def _to_largest_expense(expense: Expense | None) -> LargestExpenseSummary | None:
    if expense is None:
        return None
    return LargestExpenseSummary(
        id=expense.id,
        description=expense.description,
        amount=expense.amount,
        spent_at=expense.spent_at,
        category=LargestExpenseCategory(
            id=expense.category.id,
            name=expense.category.name,
            icon=expense.category.icon,
        ),
    )
