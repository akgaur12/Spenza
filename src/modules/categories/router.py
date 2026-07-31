"""`category_router`: system + custom expense categories for the current user.

Every route requires authentication via `CurrentUser`. Users can read every
active system category plus their own active custom categories, and can
create/update/soft-delete only their own — ownership is always derived from
`CurrentUser`, never accepted from the request body.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.core.responses import SuccessResponse
from src.modules.categories.dependencies import get_category_service
from src.modules.categories.schemas import (
    CategoryCreate,
    CategoryListResponse,
    CategoryResponse,
    CategoryUpdate,
    to_list_item,
    to_response,
)
from src.modules.categories.service import CategoryService
from src.modules.users.dependencies import CurrentUser

category_router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


@category_router.get(
    "",
    response_model=SuccessResponse[CategoryListResponse],
    summary="List active system categories plus the current user's own active categories",
)
async def list_categories(
    current_user: CurrentUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
    search: str | None = Query(default=None, min_length=1, max_length=100),
) -> SuccessResponse[CategoryListResponse]:
    categories = await category_service.list_for_user(current_user, search=search)
    return SuccessResponse(
        message="OK",
        data=CategoryListResponse(items=[to_list_item(c) for c in categories]),
    )


@category_router.get(
    "/{category_id}",
    response_model=SuccessResponse[CategoryResponse],
    summary="Get an active system category or the current user's own active category",
)
async def get_category(
    category_id: uuid.UUID,
    current_user: CurrentUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
) -> SuccessResponse[CategoryResponse]:
    category = await category_service.get_for_user(category_id, current_user)
    return SuccessResponse(message="OK", data=to_response(category))


@category_router.post(
    "",
    response_model=SuccessResponse[CategoryResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom category owned by the current user",
)
async def create_category(
    data: CategoryCreate,
    current_user: CurrentUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
) -> SuccessResponse[CategoryResponse]:
    category = await category_service.create_for_user(current_user, data)
    return SuccessResponse(message="Category created", data=to_response(category))


@category_router.patch(
    "/{category_id}",
    response_model=SuccessResponse[CategoryResponse],
    summary="Update one of the current user's own custom categories",
)
async def update_category(
    category_id: uuid.UUID,
    data: CategoryUpdate,
    current_user: CurrentUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
) -> SuccessResponse[CategoryResponse]:
    category = await category_service.update_for_user(category_id, current_user, data)
    return SuccessResponse(message="Category updated", data=to_response(category))


@category_router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete one of the current user's own custom categories",
)
async def delete_category(
    category_id: uuid.UUID,
    current_user: CurrentUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
) -> None:
    await category_service.delete_for_user(category_id, current_user)
