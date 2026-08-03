"""`expense_router`: private per-user spending records.

Every route requires authentication via `CurrentUser`. Expenses are private
user data — ownership is always derived from `CurrentUser`, never accepted
from the request body or path, and every lookup filters by owner so another
user's expense is indistinguishable from one that doesn't exist.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.core.responses import SuccessResponse
from src.modules.expenses.dependencies import get_expense_service
from src.modules.expenses.schemas import (
    ExpenseCreate,
    ExpenseListResponse,
    ExpenseResponse,
    ExpenseUpdate,
    to_response,
)
from src.modules.expenses.service import ExpenseService
from src.modules.users.dependencies import CurrentUser

expense_router = APIRouter(prefix="/api/v1/expenses", tags=["expenses"])


@expense_router.get(
    "",
    response_model=SuccessResponse[ExpenseListResponse],
    summary="List the current user's expenses, newest spending first",
)
async def list_expenses(
    current_user: CurrentUser,
    expense_service: Annotated[ExpenseService, Depends(get_expense_service)],
    category_id: Annotated[
        list[uuid.UUID] | None,
        Query(
            description="Repeat to filter by multiple categories, e.g. ?category_id=a&category_id=b"
        ),
    ] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    min_amount: Annotated[Decimal | None, Query(gt=0)] = None,
    max_amount: Annotated[Decimal | None, Query(gt=0)] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=255)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[ExpenseListResponse]:
    expenses, total = await expense_service.list_for_user(
        current_user,
        category_ids=category_id,
        start_date=start_date,
        end_date=end_date,
        min_amount=min_amount,
        max_amount=max_amount,
        search=search,
        page=page,
        page_size=page_size,
    )
    total_pages = -(-total // page_size) if total else 0
    return SuccessResponse(
        message="OK",
        data=ExpenseListResponse(
            items=[to_response(e, e.category) for e in expenses],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        ),
    )


@expense_router.get(
    "/{expense_id}",
    response_model=SuccessResponse[ExpenseResponse],
    summary="Get one of the current user's own expenses",
)
async def get_expense(
    expense_id: uuid.UUID,
    current_user: CurrentUser,
    expense_service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> SuccessResponse[ExpenseResponse]:
    expense = await expense_service.get_for_user(expense_id, current_user)
    return SuccessResponse(message="OK", data=to_response(expense, expense.category))


@expense_router.post(
    "",
    response_model=SuccessResponse[ExpenseResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Record a new expense owned by the current user",
)
async def create_expense(
    data: ExpenseCreate,
    current_user: CurrentUser,
    expense_service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> SuccessResponse[ExpenseResponse]:
    expense = await expense_service.create_for_user(current_user, data)
    return SuccessResponse(message="Expense created", data=to_response(expense, expense.category))


@expense_router.patch(
    "/{expense_id}",
    response_model=SuccessResponse[ExpenseResponse],
    summary="Update one of the current user's own expenses",
)
async def update_expense(
    expense_id: uuid.UUID,
    data: ExpenseUpdate,
    current_user: CurrentUser,
    expense_service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> SuccessResponse[ExpenseResponse]:
    expense = await expense_service.update_for_user(expense_id, current_user, data)
    return SuccessResponse(message="Expense updated", data=to_response(expense, expense.category))


@expense_router.delete(
    "/{expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete one of the current user's own expenses",
)
async def delete_expense(
    expense_id: uuid.UUID,
    current_user: CurrentUser,
    expense_service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> None:
    await expense_service.delete_for_user(expense_id, current_user)
