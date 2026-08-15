"""`admin_notification_router`: administrative notification tools —
broadcasting a system notification to some or all users, and inspecting the
delivery-log audit trail for debugging failed sends.

Every route requires the `admin` role via the existing `AdminUser`
dependency.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core.responses import SuccessResponse
from src.modules.notifications.dependencies import get_notification_service
from src.modules.notifications.enums import DeliveryChannel, DeliveryLogStatus
from src.modules.notifications.schemas import (
    BroadcastNotificationRequest,
    BroadcastNotificationResponse,
    DeliveryLogListResponse,
    delivery_log_to_response,
)
from src.modules.notifications.service import NotificationService
from src.modules.users.dependencies import AdminUser, get_user_service
from src.modules.users.service import UserService

admin_notification_router = APIRouter(prefix="/api/v1/admin/notifications", tags=["admin"])


@admin_notification_router.post(
    "/broadcast",
    response_model=SuccessResponse[BroadcastNotificationResponse],
    summary="Send a notification to a set of users, or every active user",
)
async def broadcast_notification(
    data: BroadcastNotificationRequest,
    _admin: AdminUser,
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[BroadcastNotificationResponse]:
    target_ids = data.user_ids or await user_service.list_active_user_ids()
    sent, skipped = await notification_service.broadcast(
        user_ids=target_ids,
        type=data.notification_type,
        title=data.title,
        message=data.message,
        priority=data.priority,
    )
    return SuccessResponse(
        message="Broadcast sent",
        data=BroadcastNotificationResponse(targeted=len(target_ids), sent=sent, skipped=skipped),
    )


@admin_notification_router.get(
    "/delivery-logs",
    response_model=SuccessResponse[DeliveryLogListResponse],
    summary="List recent notification delivery attempts, for debugging failed sends",
)
async def list_delivery_logs(
    _admin: AdminUser,
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
    status: Annotated[DeliveryLogStatus | None, Query()] = None,
    channel: Annotated[DeliveryChannel | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[DeliveryLogListResponse]:
    logs, total = await notification_service.list_delivery_logs(
        status=status, channel=channel, page=page, page_size=page_size
    )
    return SuccessResponse(
        message="OK",
        data=DeliveryLogListResponse(
            items=[delivery_log_to_response(log) for log in logs],
            total=total,
            page=page,
            page_size=page_size,
        ),
    )
