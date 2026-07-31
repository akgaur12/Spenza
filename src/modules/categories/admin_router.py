"""`admin_category_router`: administrative management of system categories.

Every route requires the `admin` role via the existing `AdminUser`
dependency. Only system categories (`user_id IS NULL`) are reachable here —
a user-owned category ID resolves as not-found, never modified.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.core.responses import SuccessResponse
from src.modules.categories.dependencies import get_category_service
from src.modules.categories.schemas import (
    AdminCategoryListResponse,
    AdminCategoryUpdate,
    CategoryCreate,
    CategoryResponse,
    to_response,
)
from src.modules.categories.service import CategoryService
from src.modules.users.dependencies import AdminUser

admin_category_router = APIRouter(prefix="/api/v1/admin/categories", tags=["admin"])


@admin_category_router.get(
    "",
    response_model=SuccessResponse[AdminCategoryListResponse],
    summary="List system categories, including inactive ones",
)
async def list_system_categories(
    _admin: AdminUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
    is_active: bool | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=100),
) -> SuccessResponse[AdminCategoryListResponse]:
    categories = await category_service.list_system(is_active=is_active, search=search)
    return SuccessResponse(
        message="OK",
        data=AdminCategoryListResponse(items=[to_response(c) for c in categories]),
    )


@admin_category_router.post(
    "",
    response_model=SuccessResponse[CategoryResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Create a system category, available to every user",
)
async def create_system_category(
    data: CategoryCreate,
    _admin: AdminUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
) -> SuccessResponse[CategoryResponse]:
    category = await category_service.create_system(data)
    return SuccessResponse(message="System category created", data=to_response(category))


@admin_category_router.patch(
    "/{category_id}",
    response_model=SuccessResponse[CategoryResponse],
    summary="Update a system category's name, icon, or active state",
)
async def update_system_category(
    category_id: uuid.UUID,
    data: AdminCategoryUpdate,
    _admin: AdminUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
) -> SuccessResponse[CategoryResponse]:
    category = await category_service.update_system(category_id, data)
    return SuccessResponse(message="System category updated", data=to_response(category))


@admin_category_router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete (deactivate) a system category",
)
async def delete_system_category(
    category_id: uuid.UUID,
    _admin: AdminUser,
    category_service: Annotated[CategoryService, Depends(get_category_service)],
) -> None:
    await category_service.deactivate_system(category_id)
