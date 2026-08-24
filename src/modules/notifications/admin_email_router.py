"""`admin_email_router`: email delivery configuration, and sending a
custom, admin-composed email directly to one or more specific users.

Every route requires the `admin` role via the existing `AdminUser`
dependency. `POST /send` is distinct from `POST /admin/notifications/broadcast`:
it's an ad-hoc message to named recipients (e.g. a support follow-up),
always delivered regardless of notification preferences, and never recorded
as a `Notification` — a broadcast is for a notification-shaped event, this
is for a one-off email.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.app_config import settings
from src.core.responses import SuccessResponse
from src.modules.notifications.delivery.templates import format_message_html, render_template
from src.modules.notifications.dependencies import get_email_delivery_service
from src.modules.notifications.schemas import (
    EmailConfigResponse,
    SendAdminEmailRequest,
    SendAdminEmailResponse,
)
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.users.dependencies import AdminUser, get_user_service
from src.modules.users.service import UserService

admin_email_router = APIRouter(prefix="/api/v1/admin/email", tags=["admin"])


@admin_email_router.get(
    "/config",
    response_model=SuccessResponse[EmailConfigResponse],
    summary="Current email delivery configuration (secrets redacted)",
)
async def get_email_config(_admin: AdminUser) -> SuccessResponse[EmailConfigResponse]:
    return SuccessResponse(
        message="OK",
        data=EmailConfigResponse(
            backend=settings.EMAIL_BACKEND,
            sender_name=settings.SENDER_NAME,
            sender_email=settings.active_sender_email,
            smtp_server=settings.SMTP_SERVER,
            smtp_port=settings.SMTP_PORT,
            smtp_use_tls=settings.SMTP_USE_TLS,
            resend_configured=settings.RESEND_API_KEY is not None,
            mailjet_configured=settings.MAILJET_API_KEY is not None,
            max_retries=settings.EMAIL_MAX_RETRIES,
            retry_base_delay_seconds=settings.EMAIL_RETRY_BASE_DELAY_SECONDS,
        ),
    )


@admin_email_router.post(
    "/send",
    response_model=SuccessResponse[SendAdminEmailResponse],
    summary="Send a custom email directly to one or more specific users",
)
async def send_admin_email(
    data: SendAdminEmailRequest,
    _admin: AdminUser,
    delivery_service: Annotated[EmailDeliveryService, Depends(get_email_delivery_service)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> SuccessResponse[SendAdminEmailResponse]:
    users_by_id = await user_service.get_many_by_id(set(data.user_ids))
    unknown_user_ids = [user_id for user_id in data.user_ids if user_id not in users_by_id]

    sent = 0
    failed = 0
    message_html = format_message_html(data.message)
    for user in users_by_id.values():
        html_body = render_template(
            "generic_notification.html",
            username=user.full_name or user.username,
            title=data.subject,
            message=message_html,
            payload={},
        )
        delivered = await delivery_service.send(
            to=user.email, subject=data.subject, html_body=html_body
        )
        if delivered:
            sent += 1
        else:
            failed += 1

    return SuccessResponse(
        message="Email sent",
        data=SendAdminEmailResponse(
            targeted=len(data.user_ids),
            sent=sent,
            failed=failed,
            unknown_user_ids=unknown_user_ids,
        ),
    )
