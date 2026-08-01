"""Data-access layer for the `analytics` module.

Every method is scoped to a single user and a half-open `[start, end)` UTC
time range. Two aggregation shapes cover all three analytics endpoints:

- `get_category_breakdown()` — a plain `GROUP BY category_id` (no date
  bucketing needed), reused as-is by the categories endpoint.
- `get_daily_totals()` — a `GROUP BY` on each expense's *local* calendar day,
  reused by both the calendar heatmap (which wants daily buckets directly)
  and trends (which rolls days up into weeks/months/years in the service —
  see the note on `_local_day_column` for why that roll-up happens in
  Python rather than in SQL for every interval).

Neither method loads raw expense rows into Python: the heavy reduction
(arbitrarily many expense rows down to at most a few hundred category or
day buckets) always happens in the database via `SUM`/`COUNT`/`GROUP BY`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

from src.core.app_config import settings
from src.core.money import to_money
from src.core.timezone import APP_TIMEZONE
from src.modules.categories.models import Category
from src.modules.expenses.models import Expense


def _local_day_column(
    session: AsyncSession, column: InstrumentedAttribute[datetime]
) -> ColumnElement[date]:
    """A SQL expression for the local (app-timezone) calendar date of a
    UTC-aware `spent_at` column.

    On PostgreSQL this is `CAST(timezone(:tz, column) AS DATE)`, which uses
    real IANA tzdata and is correct across DST transitions for any zone.
    SQLite (used only by the test suite; it has no timezone-name support)
    falls back to shifting by the app timezone's current fixed UTC offset
    via `strftime`. That fallback is exactly correct for the default
    `Asia/Kolkata` (which never observes DST); a DST-observing
    `APP_TIMEZONE` would only make the *test* bucketing approximate around
    a transition — production PostgreSQL is unaffected either way.
    """
    dialect_name = session.bind.dialect.name if session.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        offset_minutes = int(datetime.now(APP_TIMEZONE).utcoffset().total_seconds() // 60)  # type: ignore[union-attr]
        return func.strftime("%Y-%m-%d", column, f"{offset_minutes:+d} minutes")
    return cast(func.timezone(settings.APP_TIMEZONE, column), Date)


def _coerce_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_category_breakdown(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[Category, Decimal, int]]:
        """Every category `user_id` spent against within `[start, end)`, with
        its total and expense count, ordered by total spend descending
        (ties broken by name). Categories with no expenses in range are
        simply absent — there is nothing to divide by zero.
        """
        rows = (
            await self._session.execute(
                select(
                    Category,
                    func.sum(Expense.amount).label("total"),
                    func.count(Expense.id).label("count"),
                )
                .join(Category, Expense.category_id == Category.id)
                .where(
                    Expense.user_id == user_id,
                    Expense.spent_at >= start,
                    Expense.spent_at < end,
                )
                .group_by(Category.id)
                .order_by(func.sum(Expense.amount).desc(), Category.name)
            )
        ).all()
        return [(category, to_money(total), count) for category, total, count in rows]

    async def get_daily_totals(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[date, Decimal, int]]:
        """Per local-calendar-day totals for `user_id` within `[start, end)`,
        ordered by day. Bounded to at most one row per day in range, so this
        stays cheap even for a multi-year request.
        """
        local_day = _local_day_column(self._session, Expense.spent_at)
        rows = (
            await self._session.execute(
                select(local_day, func.sum(Expense.amount), func.count(Expense.id))
                .where(
                    Expense.user_id == user_id,
                    Expense.spent_at >= start,
                    Expense.spent_at < end,
                )
                .group_by(local_day)
                .order_by(local_day)
            )
        ).all()
        return [(_coerce_date(day), to_money(total), count) for day, total, count in rows]
