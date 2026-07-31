"""FastAPI dependency providers for the `expenses` module."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.modules.expenses.service import ExpenseService


def get_expense_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExpenseService:
    return ExpenseService(session)
