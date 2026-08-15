"""`notification_router` / `notification_preference_router`: private
per-user notifications and delivery preferences.

Every route requires authentication via `CurrentUser`. Ownership is always
derived from `CurrentUser`, never accepted from the request body or path,
and every lookup filters by owner so another user's notification is
indistinguishable from one that doesn't exist.

No creation endpoint on either router — notifications are only ever
generated internally via `NotificationService.send()` (see that module's
docstring), and a preference row is upserted implicitly by `PATCH`, never
created through a separate `POST`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.core.responses import SuccessResponse
from src.modules.notifications.delivery.templates import format_message_html, render_template
from src.modules.notifications.dependencies import (
    get_email_delivery_service,
    get_notification_preference_service,
    get_notification_service,
)
from src.modules.notifications.enums import (
    NotificationPriority,
    NotificationSortField,
    NotificationType,
    SortOrder,
)
from src.modules.notifications.exceptions import EmailDeliveryFailedError
from src.modules.notifications.preferences.service import NotificationPreferenceService
from src.modules.notifications.schemas import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationPreferenceListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    NotificationResponse,
    TestEmailResponse,
    UnreadCountResponse,
    preference_to_response,
    to_response,
)
from src.modules.notifications.service import NotificationService
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.users.dependencies import CurrentUser

notification_router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
notification_preference_router = APIRouter(
    prefix="/api/v1/notification-preferences", tags=["notification-preferences"]
)


@notification_router.get(
    "",
    response_model=SuccessResponse[NotificationListResponse],
    summary="List the current user's notifications, newest first",
)
async def list_notifications(
    current_user: CurrentUser,
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
    is_read: Annotated[bool | None, Query()] = None,
    notification_type: Annotated[NotificationType | None, Query()] = None,
    priority: Annotated[NotificationPriority | None, Query()] = None,
    sort_by: Annotated[NotificationSortField, Query()] = NotificationSortField.CREATED_AT,
    sort_order: Annotated[SortOrder, Query()] = SortOrder.DESC,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessResponse[NotificationListResponse]:
    items, total = await notification_service.list_for_user(
        current_user.id,
        is_read=is_read,
        notification_type=notification_type,
        priority=priority,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    total_pages = -(-total // page_size) if total else 0
    return SuccessResponse(
        message="OK",
        data=NotificationListResponse(
            items=[to_response(n) for n in items],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        ),
    )


@notification_router.get(
    "/unread-count",
    response_model=SuccessResponse[UnreadCountResponse],
    summary="Count the current user's unread notifications",
)
async def get_unread_count(
    current_user: CurrentUser,
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
) -> SuccessResponse[UnreadCountResponse]:
    count = await notification_service.unread_count_for_user(current_user.id)
    return SuccessResponse(message="OK", data=UnreadCountResponse(count=count))


@notification_router.patch(
    "/read-all",
    response_model=SuccessResponse[MarkAllReadResponse],
    summary="Mark every one of the current user's notifications as read",
)
async def mark_all_notifications_read(
    current_user: CurrentUser,
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
) -> SuccessResponse[MarkAllReadResponse]:
    updated = await notification_service.mark_all_read_for_user(current_user.id)
    return SuccessResponse(
        message="Notifications marked as read", data=MarkAllReadResponse(updated=updated)
    )


@notification_router.patch(
    "/{notification_id}/read",
    response_model=SuccessResponse[NotificationResponse],
    summary="Mark one of the current user's own notifications as read",
)
async def mark_notification_read(
    notification_id: uuid.UUID,
    current_user: CurrentUser,
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
) -> SuccessResponse[NotificationResponse]:
    notification = await notification_service.mark_read_for_user(notification_id, current_user.id)
    return SuccessResponse(message="Notification marked as read", data=to_response(notification))


@notification_router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Permanently delete one of the current user's own notifications",
)
async def delete_notification(
    notification_id: uuid.UUID,
    current_user: CurrentUser,
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
) -> None:
    await notification_service.delete_for_user(notification_id, current_user.id)


@notification_router.post(
    "/test-email",
    response_model=SuccessResponse[TestEmailResponse],
    summary="Send a test email to the current user to verify email delivery configuration",
)
async def send_test_email(
    current_user: CurrentUser,
    delivery_service: Annotated[EmailDeliveryService, Depends(get_email_delivery_service)],
) -> SuccessResponse[TestEmailResponse]:
    html_body = render_template(
        "generic_notification.html",
        username=current_user.full_name or current_user.username,
        title="Test Email",
        message=format_message_html(
            "This is a test email from Spenza to verify your email delivery "
            "configuration is working correctly."
        ),
        payload={},
    )
    delivered = await delivery_service.send(
        to=current_user.email, subject="Spenza test email", html_body=html_body
    )
    if not delivered:
        raise EmailDeliveryFailedError()
    return SuccessResponse(
        message="Test email sent", data=TestEmailResponse(sent_to=current_user.email)
    )


# ── Preferences ───────────────────────────────────────────────────────────


@notification_preference_router.get(
    "",
    response_model=SuccessResponse[NotificationPreferenceListResponse],
    summary="List the current user's delivery preferences for every notification type",
)
async def list_notification_preferences(
    current_user: CurrentUser,
    preference_service: Annotated[
        NotificationPreferenceService, Depends(get_notification_preference_service)
    ],
) -> SuccessResponse[NotificationPreferenceListResponse]:
    preferences = await preference_service.list_for_user(current_user.id)
    return SuccessResponse(
        message="OK",
        data=NotificationPreferenceListResponse(
            items=[preference_to_response(p) for p in preferences]
        ),
    )


@notification_preference_router.patch(
    "/{notification_type}",
    response_model=SuccessResponse[NotificationPreferenceResponse],
    summary="Update the current user's delivery preference for one notification type",
)
async def update_notification_preference(
    notification_type: NotificationType,
    data: NotificationPreferenceUpdate,
    current_user: CurrentUser,
    preference_service: Annotated[
        NotificationPreferenceService, Depends(get_notification_preference_service)
    ],
) -> SuccessResponse[NotificationPreferenceResponse]:
    updates = data.model_dump(exclude_unset=True)
    preference = await preference_service.update_for_user(
        current_user.id, notification_type, updates
    )
    return SuccessResponse(
        message="Notification preference updated", data=preference_to_response(preference)
    )
