"""`analytics_router`: aggregated spending data for charts, tables, and the
calendar heatmap, scoped to the current user only.

Every route requires authentication via `CurrentUser`; every aggregation is
scoped to `current_user.id` — there is no `user_id` query parameter and no
admin override, so an admin sees only their own analytics.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core.responses import SuccessResponse
from src.modules.analytics.dependencies import get_analytics_service
from src.modules.analytics.schemas import (
    CalendarHeatmapResponse,
    CategoryAnalyticsResponse,
    TrendAnalyticsResponse,
    TrendInterval,
)
from src.modules.analytics.service import AnalyticsService
from src.modules.users.dependencies import CurrentUser

analytics_router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@analytics_router.get(
    "/categories",
    response_model=SuccessResponse[CategoryAnalyticsResponse],
    summary="Per-category spending breakdown for a date range",
)
async def get_category_analytics(
    current_user: CurrentUser,
    analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    start_date: Annotated[
        date | None,
        Query(description="Inclusive range start. Must be given together with end_date."),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(
            description=(
                "Inclusive range end. Must be given together with start_date. "
                "If both are omitted, defaults to the full current calendar month."
            )
        ),
    ] = None,
) -> SuccessResponse[CategoryAnalyticsResponse]:
    result = await analytics_service.get_category_breakdown(current_user, start_date, end_date)
    return SuccessResponse(message="OK", data=result)


@analytics_router.get(
    "/trends",
    response_model=SuccessResponse[TrendAnalyticsResponse],
    summary="Spending trend over time, bucketed by day/week/month/year",
)
async def get_trend_analytics(
    current_user: CurrentUser,
    analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    interval: Annotated[
        TrendInterval, Query(description="Bucket granularity.")
    ] = TrendInterval.MONTHLY,
    start_date: Annotated[
        date | None,
        Query(description="Inclusive range start. Must be given together with end_date."),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(
            description=(
                "Inclusive range end. Must be given together with start_date. If both "
                "are omitted: daily defaults to the current month so far, weekly/monthly "
                "default to the current year so far, and yearly defaults to the last 5 "
                "calendar years through today."
            )
        ),
    ] = None,
) -> SuccessResponse[TrendAnalyticsResponse]:
    result = await analytics_service.get_trends(current_user, interval, start_date, end_date)
    return SuccessResponse(message="OK", data=result)


@analytics_router.get(
    "/calendar-heatmap",
    response_model=SuccessResponse[CalendarHeatmapResponse],
    summary="Daily spending for every day of a calendar year",
)
async def get_calendar_heatmap(
    current_user: CurrentUser,
    analytics_service: Annotated[AnalyticsService, Depends(get_analytics_service)],
    year: Annotated[
        int | None, Query(description="Calendar year. Defaults to the current year.")
    ] = None,
) -> SuccessResponse[CalendarHeatmapResponse]:
    result = await analytics_service.get_calendar_heatmap(current_user, year)
    return SuccessResponse(message="OK", data=result)
