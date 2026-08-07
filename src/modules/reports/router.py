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

from src.modules.reports.dependencies import get_report_service
from src.modules.reports.schemas import ReportRequest
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
