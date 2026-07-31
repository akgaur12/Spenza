"""`dashboard_router`: a read-only spending overview for the current user.

The single route requires authentication via `CurrentUser`; every
aggregation is scoped to `current_user.id` — there is no `user_id` query
parameter and no admin override, so an admin sees only their own personal
dashboard, exactly like any other user.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.responses import SuccessResponse
from src.modules.dashboard.dependencies import get_dashboard_service
from src.modules.dashboard.schemas import DashboardSummaryResponse
from src.modules.dashboard.service import DashboardService
from src.modules.users.dependencies import CurrentUser

dashboard_router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@dashboard_router.get(
    "/summary",
    response_model=SuccessResponse[DashboardSummaryResponse],
    summary="Get the current user's spending overview",
)
async def get_dashboard_summary(
    current_user: CurrentUser,
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
) -> SuccessResponse[DashboardSummaryResponse]:
    summary = await dashboard_service.get_summary(current_user)
    return SuccessResponse(message="OK", data=summary)
