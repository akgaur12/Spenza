"""`reports_router`: on-demand PDF expense reports for the current user.

A single flexible endpoint (`POST /generate`) serves every report type —
monthly, quarterly, yearly, custom — through one pipeline rather than a
route per type (see `ReportRequest`/`resolve_date_range` for how `type`
picks the period). Every route requires authentication via `CurrentUser`;
a report is always generated for the current user, never for a `user_id`
accepted from the request body.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.core.responses import SuccessResponse
from src.modules.notifications.delivery.provider import EmailAttachment
from src.modules.notifications.delivery.templates import render_template
from src.modules.notifications.dependencies import (
    get_email_delivery_service,
    get_notification_service,
)
from src.modules.notifications.enums import NotificationType
from src.modules.notifications.jobs.report_jobs import build_report_email
from src.modules.notifications.service import NotificationService
from src.modules.notifications.services.email_delivery_service import EmailDeliveryService
from src.modules.reports.dependencies import get_report_service
from src.modules.reports.exceptions import ReportEmailDeliveryFailedError
from src.modules.reports.schemas import ReportRequest, SendReportNowResponse
from src.modules.reports.service import ReportService
from src.modules.users.dependencies import CurrentUser

reports_router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@reports_router.post(
    "/generate",
    summary="Generate a PDF expense report (monthly, quarterly, yearly, or custom)",
)
async def generate_report(
    data: ReportRequest,
    current_user: CurrentUser,
    report_service: Annotated[ReportService, Depends(get_report_service)],
) -> StreamingResponse:
    return await report_service.generate(current_user, data)


@reports_router.post(
    "/send-now",
    response_model=SuccessResponse[SendReportNowResponse],
    summary="Generate a report immediately and email it to the current user",
)
async def send_report_now(
    data: ReportRequest,
    current_user: CurrentUser,
    report_service: Annotated[ReportService, Depends(get_report_service)],
    delivery_service: Annotated[EmailDeliveryService, Depends(get_email_delivery_service)],
    notification_service: Annotated[NotificationService, Depends(get_notification_service)],
) -> SuccessResponse[SendReportNowResponse]:
    pdf_bytes, report_data, filename = await report_service.generate_with_data(current_user, data)
    subject, template_name, context = build_report_email(data.type, report_data)

    notification = await notification_service.send(
        user_id=current_user.id,
        type=NotificationType.REPORT_READY,
        title=subject,
        message=(
            f"Your {report_data.metadata.period_label} expense report has been sent to your email."
        ),
        payload={"report_type": data.type.value, "period_label": report_data.metadata.period_label},
    )

    html_body = render_template(template_name, **context)
    delivered = await delivery_service.send(
        to=current_user.email,
        subject=subject,
        html_body=html_body,
        attachments=[
            EmailAttachment(filename=filename, content=pdf_bytes, mime_type="application/pdf")
        ],
        notification_id=notification.id if notification else None,
    )
    if not delivered:
        raise ReportEmailDeliveryFailedError()

    return SuccessResponse(
        message="Report generated and emailed",
        data=SendReportNowResponse(sent_to=current_user.email, filename=filename),
    )
