"""`admin_ai_assistant_router`: admin management of per-user AI assistant
access and usage limits.

Every route requires the `admin` role via the `AdminUser` dependency —
mirrors `users/admin_router.py`'s `/{user_id}/...` sub-resource pattern
(e.g. `/{user_id}/sessions`), just for the `ai-assistant` sub-resource
instead, kept in this module since the permission model/logic lives here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.responses import SuccessResponse
from src.modules.ai_assistant.dependencies import get_ai_assistant_permission_service
from src.modules.ai_assistant.permissions.schemas import (
    AIAssistantPermissionResponse,
    AIAssistantPermissionUpdate,
)
from src.modules.ai_assistant.permissions.service import AIAssistantPermissionService
from src.modules.users.dependencies import AdminUser, get_user_service
from src.modules.users.service import UserService

admin_ai_assistant_router = APIRouter(prefix="/api/v1/admin/users", tags=["admin", "ai-assistant"])


@admin_ai_assistant_router.get(
    "/{user_id}/ai-assistant",
    response_model=SuccessResponse[AIAssistantPermissionResponse],
    summary="Get a user's AI assistant access, limits, and current usage",
)
async def get_ai_assistant_permission(
    user_id: uuid.UUID,
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
    permission_service: Annotated[
        AIAssistantPermissionService, Depends(get_ai_assistant_permission_service)
    ],
) -> SuccessResponse[AIAssistantPermissionResponse]:
    await user_service.get_user_by_id(user_id)  # 404s if the target user doesn't exist
    permission = await permission_service.get_admin_view(user_id)
    return SuccessResponse(message="OK", data=permission)


@admin_ai_assistant_router.patch(
    "/{user_id}/ai-assistant",
    response_model=SuccessResponse[AIAssistantPermissionResponse],
    summary="Enable/disable a user's AI assistant access and set their limits",
)
async def update_ai_assistant_permission(
    user_id: uuid.UUID,
    data: AIAssistantPermissionUpdate,
    _admin: AdminUser,
    user_service: Annotated[UserService, Depends(get_user_service)],
    permission_service: Annotated[
        AIAssistantPermissionService, Depends(get_ai_assistant_permission_service)
    ],
) -> SuccessResponse[AIAssistantPermissionResponse]:
    await user_service.get_user_by_id(user_id)  # 404s if the target user doesn't exist
    updates = data.model_dump(exclude_unset=True)
    permission = await permission_service.update_for_user(user_id, updates)
    return SuccessResponse(message="AI assistant permission updated", data=permission)
