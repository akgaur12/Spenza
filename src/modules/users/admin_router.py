"""`admin_router`: administrative endpoints for managing user accounts.

Every route requires the `admin` role via the `AdminUser` dependency.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core.responses import SuccessResponse
from src.modules.users.dependencies import AdminUser, get_user_service
from src.modules.users.schemas import (
    AdminUserResponse,
    PaginatedUsersResponse,
    SetUserActiveRequest,
)
from src.modules.users.service import UserService

admin_router = APIRouter(prefix="/api/admin/users", tags=["admin"])


@admin_router.get(
    "",
    response_model=SuccessResponse[PaginatedUsersResponse],
    summary="List all users (paginated)",
)
async def list_users(
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SuccessResponse[PaginatedUsersResponse]:
    users, total = await user_service.list_users(page=page, page_size=page_size)
    return SuccessResponse(
        message="OK",
        data=PaginatedUsersResponse(
            items=[AdminUserResponse.model_validate(user) for user in users],
            total=total,
            page=page,
            page_size=page_size,
        ),
    )


@admin_router.get(
    "/{user_id}",
    response_model=SuccessResponse[AdminUserResponse],
    summary="Get a single user's full detail by ID",
)
async def get_user(
    user_id: uuid.UUID,
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[AdminUserResponse]:
    user = await user_service.get_user_by_id(user_id)
    return SuccessResponse(message="OK", data=AdminUserResponse.model_validate(user))


@admin_router.patch(
    "/{user_id}/active",
    response_model=SuccessResponse[AdminUserResponse],
    summary="Activate or deactivate a user account",
)
async def set_user_active(
    user_id: uuid.UUID,
    data: SetUserActiveRequest,
    admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[AdminUserResponse]:
    user = await user_service.set_user_active(user_id, data.is_active, acting_admin_id=admin.id)
    verb = "activated" if data.is_active else "deactivated"
    return SuccessResponse(message=f"User {verb}", data=AdminUserResponse.model_validate(user))


@admin_router.post(
    "/{user_id}/unlock",
    response_model=SuccessResponse[AdminUserResponse],
    summary="Clear an account lockout early",
)
async def unlock_user(
    user_id: uuid.UUID,
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[AdminUserResponse]:
    user = await user_service.unlock_user(user_id)
    return SuccessResponse(message="Account unlocked", data=AdminUserResponse.model_validate(user))


@admin_router.delete(
    "/{user_id}",
    response_model=SuccessResponse[None],
    summary="Permanently delete a user account",
)
async def delete_user(
    user_id: uuid.UUID,
    admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[None]:
    await user_service.delete_user_by_admin(user_id, acting_admin_id=admin.id)
    return SuccessResponse(message="User deleted")
