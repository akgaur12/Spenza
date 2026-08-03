"""Data-access layer for the `dashboard` module.

Every method is scoped to a single user and a half-open `[start, end)` UTC
time range — the service computes those boundaries and this layer does
nothing but aggregate in PostgreSQL (`SUM`/`COUNT`/`GROUP BY`/`ORDER BY`),
never loading a user's expenses into Python to compute totals by hand.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.money import to_money
from src.modules.categories.models import Category
from src.modules.expenses.models import Expense


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_period_summary(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> tuple[Decimal, int]:
        """Total spend and expense count for `user_id` within `[start, end)`."""
        total, count = (
            await self._session.execute(
                select(func.sum(Expense.amount), func.count(Expense.id)).where(
                    Expense.user_id == user_id,
                    Expense.spent_at >= start,
                    Expense.spent_at < end,
                )
            )
        ).one()
        return to_money(total), count or 0

    async def get_top_category(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> tuple[Category, Decimal, int] | None:
        """The category with the highest total spend for `user_id` within
        `[start, end)`, or `None` if the user has no expenses in that range.
        """
        row = (
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
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        category, total, count = row
        return category, to_money(total), count

    async def get_largest_expense(
        self, user_id: uuid.UUID, start: datetime, end: datetime
    ) -> Expense | None:
        """The single largest expense for `user_id` within `[start, end)`, with
        its category eagerly loaded, or `None` if there are none. Ties break
        deterministically on `spent_at` then `id`, both descending.
        """
        return (
            await self._session.execute(
                select(Expense)
                .where(
                    Expense.user_id == user_id,
                    Expense.spent_at >= start,
                    Expense.spent_at < end,
                )
                .options(selectinload(Expense.category))
                .order_by(Expense.amount.desc(), Expense.spent_at.desc(), Expense.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
