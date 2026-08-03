"""Business logic for the `expenses` module.

Depends only on the repository + shared infra — never on FastAPI request /
response objects — so it stays fully unit-testable.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.modules.categories.exceptions import CategoryNotFoundError
from src.modules.categories.models import Category
from src.modules.categories.repository import CategoryRepository
from src.modules.expenses.exceptions import ExpenseNotFoundError
from src.modules.expenses.models import Expense
from src.modules.expenses.repository import ExpenseRepository
from src.modules.expenses.schemas import ExpenseCreate, ExpenseUpdate
from src.modules.users.models import User

logger = get_logger(__name__)


class ExpenseService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._expenses = ExpenseRepository(session)
        self._categories = CategoryRepository(session)

    async def create_for_user(self, user: User, data: ExpenseCreate) -> Expense:
        category = await self._validate_category(data.category_id, user)
        expense = self._expenses.create(
            user_id=user.id,
            category_id=category.id,
            description=data.description,
            amount=data.amount,
            spent_at=data.spent_at,
        )
        await self._expenses.flush()
        expense.category = category
        logger.info("expense.created", expense_id=str(expense.id), user_id=str(user.id))
        return expense

    async def get_for_user(self, expense_id: uuid.UUID, user: User) -> Expense:
        expense = await self._expenses.get_by_id_for_user(expense_id, user.id)
        if expense is None:
            raise ExpenseNotFoundError()
        return expense

    async def list_for_user(
        self,
        user: User,
        *,
        category_ids: list[uuid.UUID] | None,
        start_date: date | None,
        end_date: date | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Expense], int]:
        offset = (page - 1) * page_size
        return await self._expenses.list_for_user(
            user.id,
            category_ids=category_ids,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
            offset=offset,
            limit=page_size,
        )

    async def update_for_user(
        self, expense_id: uuid.UUID, user: User, data: ExpenseUpdate
    ) -> Expense:
        expense = await self._get_owned_by_user(expense_id, user)
        updates = data.model_dump(exclude_unset=True)

        new_category_id = updates.pop("category_id", None)
        if new_category_id is not None:
            category = await self._validate_category(new_category_id, user)
            expense.category_id = category.id
            expense.category = category

        for field, value in updates.items():
            setattr(expense, field, value)

        await self._expenses.flush()
        logger.info("expense.updated", expense_id=str(expense.id), user_id=str(user.id))
        return expense

    async def delete_for_user(self, expense_id: uuid.UUID, user: User) -> None:
        expense = await self._get_owned_by_user(expense_id, user)
        await self._expenses.delete(expense)
        await self._expenses.flush()
        logger.info("expense.deleted", expense_id=str(expense_id), user_id=str(user.id))

    async def _get_owned_by_user(self, expense_id: uuid.UUID, user: User) -> Expense:
        expense = await self._expenses.get_by_id_for_user(expense_id, user.id)
        if expense is None:
            raise ExpenseNotFoundError()
        return expense

    async def _validate_category(self, category_id: uuid.UUID, user: User) -> Category:
        """A category is usable on an expense only if it's active, and is
        either a system category (`user_id is None`) or owned by the same
        user. Any other outcome — missing, inactive, or another user's
        category — is reported identically as not-found, so a request can
        never distinguish "doesn't exist" from "exists but isn't yours".
        """
        category = await self._categories.get_by_id(category_id)
        if category is None or not category.is_active:
            raise CategoryNotFoundError()
        if category.user_id is not None and category.user_id != user.id:
            raise CategoryNotFoundError()
        return category
