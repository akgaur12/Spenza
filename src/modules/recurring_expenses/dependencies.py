"""FastAPI dependency providers for the `recurring_expenses` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.recurring_expenses.service import RecurringExpenseService


def get_recurring_expense_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RecurringExpenseService:
    return RecurringExpenseService(session)
