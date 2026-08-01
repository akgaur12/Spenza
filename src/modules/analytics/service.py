"""Business logic for the `analytics` module.

Date-range resolution, timezone-aware boundaries, and interval bucketing all
live here; the repository only runs `SUM`/`COUNT`/`GROUP BY` queries.

Trend/heatmap bucketing strategy: `AnalyticsRepository.get_daily_totals()`
does the expensive reduction in SQL (arbitrarily many expense rows down to
at most a few hundred local-calendar-day buckets, bounded by
`MAX_TREND_RANGE_DAYS`). Daily/monthly/yearly trend buckets could be grouped
directly in SQL too, but weekly buckets need a Monday-anchored ISO week,
which SQLite (used only by the test suite) has no portable equivalent for —
so all four intervals are rolled up from the same SQL-aggregated daily
buckets here, which is cheap since there are at most ~7300 of them even for
a 20-year range. This keeps the Monday-Sunday week convention identical to
the dashboard module (`src.core.periods`) and fully testable.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.periods import end_of_month, start_of_month, start_of_week, start_of_year
from src.core.timezone import APP_TIMEZONE
from src.modules.analytics.exceptions import (
    DateRangeTooLargeError,
    IncompleteDateRangeError,
    InvalidDateRangeError,
    InvalidYearError,
)
from src.modules.analytics.repository import AnalyticsRepository
from src.modules.analytics.schemas import (
    CalendarHeatmapDay,
    CalendarHeatmapResponse,
    CategoryAnalyticsItem,
    CategoryAnalyticsResponse,
    TrendAnalyticsResponse,
    TrendDataPoint,
    TrendInterval,
)
from src.modules.users.models import User

_CENTS = Decimal("0.01")
_PERCENT = Decimal("0.01")

# Bounds the number of local-calendar-day buckets a single trends request can
# force the repository to aggregate (~20 years' worth), preventing an
# unbounded range from generating an excessively large response.
MAX_TREND_RANGE_DAYS = 366 * 20

# Documented, bounded default when `interval=yearly` and no range is given
# (avoids an extra query to find the user's earliest expense).
YEARLY_DEFAULT_SPAN_YEARS = 5

MIN_HEATMAP_YEAR = 2000


def _local_midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=APP_TIMEZONE).astimezone(UTC)


def _validate_date_range(start_date: date | None, end_date: date | None) -> None:
    if (start_date is None) != (end_date is None):
        raise IncompleteDateRangeError()
    if start_date is not None and end_date is not None and start_date > end_date:
        raise InvalidDateRangeError()


def _validate_range_size(start_date: date, end_date: date) -> None:
    span_days = (end_date - start_date).days + 1
    if span_days > MAX_TREND_RANGE_DAYS:
        raise DateRangeTooLargeError(
            f"Date range too large: {span_days} days requested, maximum is "
            f"{MAX_TREND_RANGE_DAYS} days (~{MAX_TREND_RANGE_DAYS // 366} years)."
        )


def _validate_year(year: int, current_year: int) -> None:
    if not (MIN_HEATMAP_YEAR <= year <= current_year + 1):
        raise InvalidYearError(f"year must be between {MIN_HEATMAP_YEAR} and {current_year + 1}.")


def _resolve_category_range(
    start_date: date | None, end_date: date | None, now_local: datetime
) -> tuple[date, date]:
    """Both boundaries given -> use them as-is. Neither given -> the full
    current calendar month (including its not-yet-elapsed days, since this
    is a static reporting range rather than a live running total like the
    dashboard summary). Exactly one given is rejected: a predictable API
    requires both or neither.
    """
    _validate_date_range(start_date, end_date)
    if start_date is not None and end_date is not None:
        return start_date, end_date
    return start_of_month(now_local).date(), end_of_month(now_local)


def _resolve_trend_range(
    interval: TrendInterval, start_date: date | None, end_date: date | None, now_local: datetime
) -> tuple[date, date]:
    """Both boundaries given -> use them (validated against
    `MAX_TREND_RANGE_DAYS`). Neither given -> an interval-appropriate
    default ending today: daily -> current month so far, weekly/monthly ->
    current year so far, yearly -> the last `YEARLY_DEFAULT_SPAN_YEARS`
    calendar years through today.
    """
    _validate_date_range(start_date, end_date)
    if start_date is not None and end_date is not None:
        _validate_range_size(start_date, end_date)
        return start_date, end_date

    today = now_local.date()
    if interval is TrendInterval.DAILY:
        return start_of_month(now_local).date(), today
    if interval in (TrendInterval.WEEKLY, TrendInterval.MONTHLY):
        return start_of_year(now_local).date(), today
    return date(today.year - YEARLY_DEFAULT_SPAN_YEARS + 1, 1, 1), today


def _bucket_start(interval: TrendInterval, day: date) -> date:
    if interval is TrendInterval.DAILY:
        return day
    local_dt = datetime(day.year, day.month, day.day, tzinfo=APP_TIMEZONE)
    if interval is TrendInterval.WEEKLY:
        return start_of_week(local_dt).date()
    if interval is TrendInterval.MONTHLY:
        return start_of_month(local_dt).date()
    return date(day.year, 1, 1)  # yearly


def _all_bucket_starts(interval: TrendInterval, start_date: date, end_date: date) -> list[date]:
    """Every distinct bucket start date covering `[start_date, end_date]`, in
    chronological order — derived purely from calendar math (not from which
    days actually have expenses), so zero-spend buckets still appear.
    """
    starts: list[date] = []
    seen: set[date] = set()
    day = start_date
    while day <= end_date:
        bucket_start = _bucket_start(interval, day)
        if bucket_start not in seen:
            seen.add(bucket_start)
            starts.append(bucket_start)
        day += timedelta(days=1)
    return starts


def _format_period(
    interval: TrendInterval, bucket_start: date
) -> tuple[str, date | None, date | None]:
    if interval is TrendInterval.DAILY:
        return bucket_start.isoformat(), None, None
    if interval is TrendInterval.WEEKLY:
        iso_year, iso_week, _ = bucket_start.isocalendar()
        return f"{iso_year}-W{iso_week:02d}", bucket_start, bucket_start + timedelta(days=6)
    if interval is TrendInterval.MONTHLY:
        return f"{bucket_start.year:04d}-{bucket_start.month:02d}", None, None
    return f"{bucket_start.year:04d}", None, None


def _average_expense(total: Decimal, count: int) -> Decimal:
    if count == 0:
        return Decimal("0.00")
    return (total / count).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _percentage(part: Decimal, whole: Decimal) -> float:
    if whole == 0:
        return 0.0
    return float((part / whole * 100).quantize(_PERCENT, rounding=ROUND_HALF_UP))


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AnalyticsRepository(session)

    async def get_category_breakdown(
        self, user: User, start_date: date | None, end_date: date | None
    ) -> CategoryAnalyticsResponse:
        now_local = datetime.now(APP_TIMEZONE)
        resolved_start, resolved_end = _resolve_category_range(start_date, end_date, now_local)

        rows = await self._repo.get_category_breakdown(
            user.id,
            _local_midnight_utc(resolved_start),
            _local_midnight_utc(resolved_end + timedelta(days=1)),
        )

        total_spending = sum((total for _, total, _ in rows), Decimal("0.00"))
        expense_count = sum(count for _, _, count in rows)

        items = [
            CategoryAnalyticsItem(
                category_id=category.id,
                name=category.name,
                icon=category.icon,
                total=total,
                expense_count=count,
                percentage=_percentage(total, total_spending),
                average_expense=_average_expense(total, count),
            )
            for category, total, count in rows
        ]

        return CategoryAnalyticsResponse(
            start_date=resolved_start,
            end_date=resolved_end,
            total_spending=total_spending,
            expense_count=expense_count,
            categories=items,
        )

    async def get_trends(
        self,
        user: User,
        interval: TrendInterval,
        start_date: date | None,
        end_date: date | None,
    ) -> TrendAnalyticsResponse:
        now_local = datetime.now(APP_TIMEZONE)
        resolved_start, resolved_end = _resolve_trend_range(
            interval, start_date, end_date, now_local
        )

        daily_totals = await self._repo.get_daily_totals(
            user.id,
            _local_midnight_utc(resolved_start),
            _local_midnight_utc(resolved_end + timedelta(days=1)),
        )

        bucket_amounts: dict[date, Decimal] = {}
        bucket_counts: dict[date, int] = {}
        for day, total, count in daily_totals:
            bucket_start = _bucket_start(interval, day)
            bucket_amounts[bucket_start] = bucket_amounts.get(bucket_start, Decimal("0.00")) + total
            bucket_counts[bucket_start] = bucket_counts.get(bucket_start, 0) + count

        data = []
        for bucket_start in _all_bucket_starts(interval, resolved_start, resolved_end):
            total = bucket_amounts.get(bucket_start, Decimal("0.00"))
            count = bucket_counts.get(bucket_start, 0)
            period, point_start, point_end = _format_period(interval, bucket_start)
            data.append(
                TrendDataPoint(
                    period=period,
                    start_date=point_start,
                    end_date=point_end,
                    total=total,
                    expense_count=count,
                    average_expense=_average_expense(total, count),
                )
            )

        total_spending = sum((total for _, total, _ in daily_totals), Decimal("0.00"))
        expense_count = sum(count for _, _, count in daily_totals)

        return TrendAnalyticsResponse(
            interval=interval,
            start_date=resolved_start,
            end_date=resolved_end,
            total_spending=total_spending,
            expense_count=expense_count,
            data=data,
        )

    async def get_calendar_heatmap(self, user: User, year: int | None) -> CalendarHeatmapResponse:
        now_local = datetime.now(APP_TIMEZONE)
        current_year = now_local.year
        resolved_year = year if year is not None else current_year
        _validate_year(resolved_year, current_year)

        year_start = date(resolved_year, 1, 1)
        next_year_start = date(resolved_year + 1, 1, 1)

        daily_totals = await self._repo.get_daily_totals(
            user.id, _local_midnight_utc(year_start), _local_midnight_utc(next_year_start)
        )
        totals_by_day = {day: (total, count) for day, total, count in daily_totals}

        today_local = now_local.date()
        data = []
        day = year_start
        while day < next_year_start:
            total, count = totals_by_day.get(day, (Decimal("0.00"), 0))
            data.append(
                CalendarHeatmapDay(
                    date=day,
                    month=day.month,
                    day=day.day,
                    total=total,
                    expense_count=count,
                    is_future=day > today_local,
                )
            )
            day += timedelta(days=1)

        total_spending = sum((d.total for d in data), Decimal("0.00"))
        expense_count = sum(d.expense_count for d in data)
        max_daily_spending = max((d.total for d in data), default=Decimal("0.00"))

        return CalendarHeatmapResponse(
            year=resolved_year,
            total_spending=total_spending,
            expense_count=expense_count,
            max_daily_spending=max_daily_spending,
            data=data,
        )
