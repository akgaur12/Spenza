"""Data-access layer for the `expenses` module.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns. `ExpenseService` composes these to implement
behavior. Filtering, sorting, and pagination all happen in SQL; nothing is
paginated in Python.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.modules.expenses.models import Expense


class ExpenseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id_for_user(self, expense_id: uuid.UUID, user_id: uuid.UUID) -> Expense | None:
        result = await self._session.execute(
            select(Expense)
            .where(Expense.id == expense_id, Expense.user_id == user_id)
            .options(selectinload(Expense.category))
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        category_id: uuid.UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Expense], int]:
        conditions = self._build_conditions(
            user_id,
            category_id=category_id,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
        )

        total = await self._session.scalar(
            select(func.count()).select_from(Expense).where(*conditions)
        )

        result = await self._session.execute(
            select(Expense)
            .where(*conditions)
            .options(selectinload(Expense.category))
            .order_by(Expense.spent_at.desc(), Expense.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    def _build_conditions(
        self,
        user_id: uuid.UUID,
        *,
        category_id: uuid.UUID | None,
        start_date: date | None,
        end_date: date | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        search: str | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [Expense.user_id == user_id]
        if category_id is not None:
            conditions.append(Expense.category_id == category_id)
        if start_date is not None:
            conditions.append(
                Expense.spent_at >= datetime.combine(start_date, time.min, tzinfo=UTC)
            )
        if end_date is not None:
            exclusive_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
            conditions.append(Expense.spent_at < exclusive_end)
        if min_amount is not None:
            conditions.append(Expense.amount >= min_amount)
        if max_amount is not None:
            conditions.append(Expense.amount <= max_amount)
        if search:
            conditions.append(func.lower(Expense.description).like(f"%{search.lower()}%"))
        return conditions

    def create(
        self,
        *,
        user_id: uuid.UUID,
        category_id: uuid.UUID,
        description: str,
        amount: Decimal,
        spent_at: datetime,
    ) -> Expense:
        expense = Expense(
            user_id=user_id,
            category_id=category_id,
            description=description,
            amount=amount,
            spent_at=spent_at,
        )
        self._session.add(expense)
        return expense

    async def delete(self, expense: Expense) -> None:
        await self._session.delete(expense)

    async def flush(self) -> None:
        await self._session.flush()
