"""Data-access layer for the `expenses` module.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns. `ExpenseService` composes these to implement
behavior. Filtering, sorting, and pagination all happen in SQL; nothing is
paginated in Python.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.timezone import local_midnight_utc
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
        category_ids: list[uuid.UUID] | None = None,
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
            category_ids=category_ids,
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
        category_ids: list[uuid.UUID] | None,
        start_date: date | None,
        end_date: date | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        search: str | None,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [Expense.user_id == user_id]
        if category_ids:
            conditions.append(Expense.category_id.in_(category_ids))
        if start_date is not None:
            conditions.append(Expense.spent_at >= local_midnight_utc(start_date))
        if end_date is not None:
            conditions.append(Expense.spent_at < local_midnight_utc(end_date + timedelta(days=1)))
        if min_amount is not None:
            conditions.append(Expense.amount >= min_amount)
        if max_amount is not None:
            conditions.append(Expense.amount <= max_amount)
        if search:
            conditions.append(func.lower(Expense.description).like(f"%{search.lower()}%"))
        return conditions

    async def list_for_export(
        self,
        user_id: uuid.UUID,
        *,
        category_ids: list[uuid.UUID] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
        search: str | None = None,
        limit: int = 50_000,
    ) -> list[Expense]:
        """All matching expenses, oldest spending first — the chronological
        order reports/spreadsheets want, unlike `list_for_user`'s
        newest-first history view. Capped by `limit` (see
        `settings.MAX_EXPORT_ROWS`) rather than paginated, since an export is
        a single file, not a paged UI.
        """
        conditions = self._build_conditions(
            user_id,
            category_ids=category_ids,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
        )
        result = await self._session.execute(
            select(Expense)
            .where(*conditions)
            .options(selectinload(Expense.category))
            .order_by(Expense.spent_at.asc(), Expense.created_at.asc(), Expense.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def exists_duplicate(
        self,
        user_id: uuid.UUID,
        *,
        category_id: uuid.UUID,
        description: str,
        amount: Decimal,
        spent_at: datetime,
    ) -> bool:
        """True if the user already has an expense with the exact same
        category, description, amount, and spend timestamp. Used by the
        import preview to flag likely-duplicate rows — an exact match on all
        four fields, not a fuzzy heuristic, so two genuinely distinct
        expenses that happen to share these values are a rare enough
        coincidence that flagging them is an acceptable tradeoff.
        """
        result = await self._session.execute(
            select(Expense.id)
            .where(
                Expense.user_id == user_id,
                Expense.category_id == category_id,
                Expense.description == description,
                Expense.amount == amount,
                Expense.spent_at == spent_at,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

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
