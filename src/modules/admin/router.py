"""`admin_stats_router`: a system-wide metrics overview for admins.

Unlike `dashboard`/`analytics` (deliberately own-data-only, see their module
docstrings), this endpoint aggregates across every user — it's the
business-visibility counterpart those modules intentionally don't provide.
Requires the `admin` role via the existing `AdminUser` dependency.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from src.core.responses import SuccessResponse
from src.modules.admin.dependencies import get_admin_stats_service
from src.modules.admin.schemas import AdminStatsOverview
from src.modules.admin.service import AdminStatsService
from src.modules.users.dependencies import AdminUser

admin_stats_router = APIRouter(prefix="/api/v1/admin/stats", tags=["admin"])


@admin_stats_router.get(
    "/overview",
    response_model=SuccessResponse[AdminStatsOverview],
    summary="System-wide counts across users, expenses, categories, and notifications",
)
async def get_stats_overview(
    _admin: AdminUser,
    stats_service: Annotated[AdminStatsService, Depends(get_admin_stats_service)],
) -> SuccessResponse[AdminStatsOverview]:
    overview = await stats_service.get_overview()
    return SuccessResponse(message="OK", data=overview)
