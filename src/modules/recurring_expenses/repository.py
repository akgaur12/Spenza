"""Data-access layer for the `recurring_expenses` module.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns. `RecurringExpenseService` composes these to
implement behavior. Filtering, sorting, and pagination all happen in SQL.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from src.modules.categories.models import Category
from src.modules.recurring_expenses.enums import (
    Frequency,
    GenerationMode,
    RecurringExpenseSortField,
    RecurringExpenseStatus,
    SortOrder,
)
from src.modules.recurring_expenses.models import RecurringExpense

_SORT_COLUMNS: dict[RecurringExpenseSortField, InstrumentedAttribute[Any]] = {
    RecurringExpenseSortField.CREATED_AT: RecurringExpense.created_at,
    RecurringExpenseSortField.NEXT_RUN_DATE: RecurringExpense.next_run_date,
    RecurringExpenseSortField.AMOUNT: RecurringExpense.amount,
    RecurringExpenseSortField.DESCRIPTION: RecurringExpense.description,
}


class RecurringExpenseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id_for_user(
        self, recurring_id: uuid.UUID, user_id: uuid.UUID
    ) -> RecurringExpense | None:
        result = await self._session.execute(
            select(RecurringExpense)
            .where(RecurringExpense.id == recurring_id, RecurringExpense.user_id == user_id)
            .options(selectinload(RecurringExpense.category))
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: RecurringExpenseStatus | None = None,
        frequency: Frequency | None = None,
        generation_mode: GenerationMode | None = None,
        search: str | None = None,
        sort_by: RecurringExpenseSortField = RecurringExpenseSortField.CREATED_AT,
        sort_order: SortOrder = SortOrder.DESC,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[RecurringExpense], int]:
        conditions: list[ColumnElement[bool]] = [RecurringExpense.user_id == user_id]
        if status is not None:
            conditions.append(RecurringExpense.status == status)
        if frequency is not None:
            conditions.append(RecurringExpense.frequency == frequency)
        if generation_mode is not None:
            conditions.append(RecurringExpense.generation_mode == generation_mode)

        # Search spans both the recurring expense's own description and its
        # category's name — a join is only needed for the latter half.
        query = select(RecurringExpense).join(RecurringExpense.category)
        count_query = (
            select(func.count()).select_from(RecurringExpense).join(RecurringExpense.category)
        )
        if search:
            pattern = f"%{search.lower()}%"
            search_condition = func.lower(RecurringExpense.description).like(pattern) | func.lower(
                Category.name
            ).like(pattern)
            conditions.append(search_condition)

        total = await self._session.scalar(count_query.where(*conditions))

        sort_column = _SORT_COLUMNS[sort_by]
        order = sort_column.asc() if sort_order is SortOrder.ASC else sort_column.desc()

        result = await self._session.execute(
            query.where(*conditions)
            .options(selectinload(RecurringExpense.category))
            .order_by(order, RecurringExpense.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def find_due(self, today: date) -> list[RecurringExpense]:
        """Every `ACTIVE` recurring expense whose `next_run_date` has
        arrived, across all users — the scheduler's daily job processes
        exactly this set. Ordered by id for a stable, deterministic
        processing order across runs.
        """
        result = await self._session.execute(
            select(RecurringExpense)
            .where(
                RecurringExpense.status == RecurringExpenseStatus.ACTIVE,
                RecurringExpense.next_run_date <= today,
            )
            .order_by(RecurringExpense.id)
        )
        return list(result.scalars().all())

    def create(
        self,
        *,
        user_id: uuid.UUID,
        category_id: uuid.UUID,
        description: str,
        amount: Decimal,
        frequency: Frequency,
        generation_mode: GenerationMode,
        start_date: date,
        end_date: date | None,
        next_run_date: date,
    ) -> RecurringExpense:
        recurring = RecurringExpense(
            user_id=user_id,
            category_id=category_id,
            description=description,
            amount=amount,
            frequency=frequency,
            generation_mode=generation_mode,
            status=RecurringExpenseStatus.ACTIVE,
            start_date=start_date,
            end_date=end_date,
            next_run_date=next_run_date,
            last_run_date=None,
        )
        self._session.add(recurring)
        return recurring

    async def delete(self, recurring: RecurringExpense) -> None:
        await self._session.delete(recurring)

    async def flush(self) -> None:
        await self._session.flush()
