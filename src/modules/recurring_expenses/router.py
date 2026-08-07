"""`recurring_expense_router`: private per-user expense templates.

Every route requires authentication via `CurrentUser`. Recurring expenses
are private user data — ownership is always derived from `CurrentUser`,
never accepted from the request body or path, and every lookup filters by
owner so another user's recurring expense is indistinguishable from one
that doesn't exist.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.core.responses import SuccessResponse
from src.modules.recurring_expenses.dependencies import get_recurring_expense_service
from src.modules.recurring_expenses.enums import (
    Frequency,
    GenerationMode,
    RecurringExpenseSortField,
    RecurringExpenseStatus,
    SortOrder,
)
from src.modules.recurring_expenses.schemas import (
    RecurringExpenseCreate,
    RecurringExpenseListResponse,
    RecurringExpenseResponse,
    RecurringExpenseUpdate,
    to_response,
)
from src.modules.recurring_expenses.service import RecurringExpenseService
from src.modules.users.dependencies import CurrentUser

recurring_expense_router = APIRouter(
    prefix="/api/v1/recurring-expenses", tags=["recurring-expenses"]
)


@recurring_expense_router.get(
    "",
    response_model=SuccessResponse[RecurringExpenseListResponse],
    summary="List the current user's recurring expenses, newest first",
)
async def list_recurring_expenses(
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
    status_filter: Annotated[RecurringExpenseStatus | None, Query(alias="status")] = None,
    frequency: Annotated[Frequency | None, Query()] = None,
    generation_mode: Annotated[GenerationMode | None, Query()] = None,
    search: Annotated[
        str | None,
        Query(min_length=1, max_length=255, description="Matches description or category"),
    ] = None,
    sort_by: Annotated[RecurringExpenseSortField, Query()] = RecurringExpenseSortField.CREATED_AT,
    sort_order: Annotated[SortOrder, Query()] = SortOrder.DESC,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[RecurringExpenseListResponse]:
    items, total = await recurring_service.list_for_user(
        current_user,
        status=status_filter,
        frequency=frequency,
        generation_mode=generation_mode,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    total_pages = -(-total // page_size) if total else 0
    return SuccessResponse(
        message="OK",
        data=RecurringExpenseListResponse(
            items=[to_response(r, r.category) for r in items],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        ),
    )


@recurring_expense_router.get(
    "/{recurring_expense_id}",
    response_model=SuccessResponse[RecurringExpenseResponse],
    summary="Get one of the current user's own recurring expenses",
)
async def get_recurring_expense(
    recurring_expense_id: uuid.UUID,
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
) -> SuccessResponse[RecurringExpenseResponse]:
    recurring = await recurring_service.get_for_user(recurring_expense_id, current_user)
    return SuccessResponse(message="OK", data=to_response(recurring, recurring.category))


@recurring_expense_router.post(
    "",
    response_model=SuccessResponse[RecurringExpenseResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a new recurring expense template owned by the current user",
)
async def create_recurring_expense(
    data: RecurringExpenseCreate,
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
) -> SuccessResponse[RecurringExpenseResponse]:
    recurring = await recurring_service.create_for_user(current_user, data)
    return SuccessResponse(
        message="Recurring expense created", data=to_response(recurring, recurring.category)
    )


@recurring_expense_router.patch(
    "/{recurring_expense_id}",
    response_model=SuccessResponse[RecurringExpenseResponse],
    summary="Update one of the current user's own recurring expenses",
)
async def update_recurring_expense(
    recurring_expense_id: uuid.UUID,
    data: RecurringExpenseUpdate,
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
) -> SuccessResponse[RecurringExpenseResponse]:
    recurring = await recurring_service.update_for_user(recurring_expense_id, current_user, data)
    return SuccessResponse(
        message="Recurring expense updated", data=to_response(recurring, recurring.category)
    )


@recurring_expense_router.delete(
    "/{recurring_expense_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete one of the current user's own recurring expenses",
)
async def delete_recurring_expense(
    recurring_expense_id: uuid.UUID,
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
) -> None:
    await recurring_service.delete_for_user(recurring_expense_id, current_user)


@recurring_expense_router.patch(
    "/{recurring_expense_id}/pause",
    response_model=SuccessResponse[RecurringExpenseResponse],
    summary="Pause an active recurring expense — the scheduler will skip it",
)
async def pause_recurring_expense(
    recurring_expense_id: uuid.UUID,
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
) -> SuccessResponse[RecurringExpenseResponse]:
    recurring = await recurring_service.pause_for_user(recurring_expense_id, current_user)
    return SuccessResponse(
        message="Recurring expense paused", data=to_response(recurring, recurring.category)
    )


@recurring_expense_router.patch(
    "/{recurring_expense_id}/resume",
    response_model=SuccessResponse[RecurringExpenseResponse],
    summary="Resume a paused recurring expense",
)
async def resume_recurring_expense(
    recurring_expense_id: uuid.UUID,
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
) -> SuccessResponse[RecurringExpenseResponse]:
    recurring = await recurring_service.resume_for_user(recurring_expense_id, current_user)
    return SuccessResponse(
        message="Recurring expense resumed", data=to_response(recurring, recurring.category)
    )


@recurring_expense_router.post(
    "/{recurring_expense_id}/run",
    response_model=SuccessResponse[RecurringExpenseResponse],
    summary="Force-process the recurring expense's currently pending occurrence now",
)
async def run_recurring_expense(
    recurring_expense_id: uuid.UUID,
    current_user: CurrentUser,
    recurring_service: Annotated[RecurringExpenseService, Depends(get_recurring_expense_service)],
) -> SuccessResponse[RecurringExpenseResponse]:
    recurring = await recurring_service.run_now_for_user(recurring_expense_id, current_user)
    return SuccessResponse(
        message="Recurring expense processed", data=to_response(recurring, recurring.category)
    )
