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
    RevokedSessionsResponse,
    SessionInfo,
    SessionListResponse,
    SetUserActiveRequest,
    UpdateUserRoleRequest,
)
from src.modules.users.service import UserService

admin_router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])


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


@admin_router.patch(
    "/{user_id}/role",
    response_model=SuccessResponse[AdminUserResponse],
    summary="Promote or demote a user's role",
)
async def update_user_role(
    user_id: uuid.UUID,
    data: UpdateUserRoleRequest,
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[AdminUserResponse]:
    user = await user_service.update_user_role(user_id, data.role)
    return SuccessResponse(message="User role updated", data=AdminUserResponse.model_validate(user))


@admin_router.get(
    "/{user_id}/sessions",
    response_model=SuccessResponse[SessionListResponse],
    summary="List a user's active sessions (devices currently logged in)",
)
async def list_user_sessions(
    user_id: uuid.UUID,
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[SessionListResponse]:
    sessions = await user_service.list_sessions_for_user(user_id)
    return SuccessResponse(
        message="OK",
        data=SessionListResponse(items=[SessionInfo.model_validate(s) for s in sessions]),
    )


@admin_router.delete(
    "/{user_id}/sessions",
    response_model=SuccessResponse[RevokedSessionsResponse],
    summary="Force-revoke every active session for a user (sign them out everywhere)",
)
async def revoke_user_sessions(
    user_id: uuid.UUID,
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[RevokedSessionsResponse]:
    revoked = await user_service.admin_revoke_sessions(user_id)
    return SuccessResponse(
        message="Sessions revoked", data=RevokedSessionsResponse(revoked=revoked)
    )


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
