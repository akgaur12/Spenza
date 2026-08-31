"""`admin_ai_assistant_observability_router`: cross-user AI assistant
monitoring for admins — usage over time, provider/model breakdowns, and a
per-user usage table. Every route requires the `admin` role via the
existing `AdminUser` dependency. The single-user counterpart (`GET`/`PATCH`
`.../users/{user_id}/ai-assistant`) lives in `ai_assistant.admin_router`.

Every route also accepts an optional `user_id` query param, scoping its
usual system-wide totals/charts/table to just that one user instead —
useful for drilling into one user's usage without leaving this dashboard.
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from src.core.responses import SuccessResponse
from src.modules.ai_assistant.dependencies import get_ai_assistant_observability_service
from src.modules.ai_assistant.enums import ChatRunStatus, LLMProvider
from src.modules.ai_assistant.observability.schemas import (
    AIAssistantMessageLogListResponse,
    AIAssistantOverview,
    AIAssistantProviderUsageResponse,
    AIAssistantUsageTimeseries,
    AIAssistantUserUsageListResponse,
)
from src.modules.ai_assistant.observability.service import (
    AIAssistantObservabilityService,
    UserUsageSortField,
)
from src.modules.analytics.schemas import TrendInterval
from src.modules.recurring_expenses.enums import SortOrder
from src.modules.users.dependencies import AdminUser

admin_ai_assistant_observability_router = APIRouter(
    prefix="/api/v1/admin/ai-assistant", tags=["admin", "ai-assistant"]
)

_UserIdFilter = Annotated[
    uuid.UUID | None,
    Query(description="Scope this endpoint to a single user instead of system-wide."),
]


@admin_ai_assistant_observability_router.get(
    "/overview",
    response_model=SuccessResponse[AIAssistantOverview],
    summary="System-wide AI assistant usage: chats, messages, runs, tokens, active users",
)
async def get_ai_assistant_overview(
    _admin: AdminUser,
    observability_service: Annotated[
        AIAssistantObservabilityService, Depends(get_ai_assistant_observability_service)
    ],
    user_id: _UserIdFilter = None,
) -> SuccessResponse[AIAssistantOverview]:
    overview = await observability_service.get_overview(user_id)
    return SuccessResponse(message="OK", data=overview)


@admin_ai_assistant_observability_router.get(
    "/usage/timeseries",
    response_model=SuccessResponse[AIAssistantUsageTimeseries],
    summary="Messages/runs/tokens over time, bucketed daily/weekly/monthly/yearly",
)
async def get_ai_assistant_usage_timeseries(
    _admin: AdminUser,
    observability_service: Annotated[
        AIAssistantObservabilityService, Depends(get_ai_assistant_observability_service)
    ],
    interval: Annotated[TrendInterval, Query()] = TrendInterval.DAILY,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    user_id: _UserIdFilter = None,
) -> SuccessResponse[AIAssistantUsageTimeseries]:
    timeseries = await observability_service.get_usage_timeseries(
        interval, start_date, end_date, user_id
    )
    return SuccessResponse(message="OK", data=timeseries)


@admin_ai_assistant_observability_router.get(
    "/providers",
    response_model=SuccessResponse[AIAssistantProviderUsageResponse],
    summary="Usage broken down by provider and model for a date range",
)
async def get_ai_assistant_provider_usage(
    _admin: AdminUser,
    observability_service: Annotated[
        AIAssistantObservabilityService, Depends(get_ai_assistant_observability_service)
    ],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    user_id: _UserIdFilter = None,
) -> SuccessResponse[AIAssistantProviderUsageResponse]:
    usage = await observability_service.get_provider_usage(start_date, end_date, user_id)
    return SuccessResponse(message="OK", data=usage)


@admin_ai_assistant_observability_router.get(
    "/users",
    response_model=SuccessResponse[AIAssistantUserUsageListResponse],
    summary="Per-user AI assistant usage (only users who have used the assistant)",
)
async def get_ai_assistant_user_usage(
    _admin: AdminUser,
    observability_service: Annotated[
        AIAssistantObservabilityService, Depends(get_ai_assistant_observability_service)
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: Annotated[UserUsageSortField, Query()] = "messages_sent",
    order: Annotated[SortOrder, Query()] = SortOrder.DESC,
    user_id: _UserIdFilter = None,
) -> SuccessResponse[AIAssistantUserUsageListResponse]:
    usage = await observability_service.get_user_usage(
        page=page, page_size=page_size, sort_by=sort_by, order=order, user_id=user_id
    )
    return SuccessResponse(message="OK", data=usage)


@admin_ai_assistant_observability_router.get(
    "/logs",
    response_model=SuccessResponse[AIAssistantMessageLogListResponse],
    summary="Per-message log: who sent it, input/output text, tokens, and estimated cost",
)
async def get_ai_assistant_message_logs(
    _admin: AdminUser,
    observability_service: Annotated[
        AIAssistantObservabilityService, Depends(get_ai_assistant_observability_service)
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[ChatRunStatus | None, Query()] = None,
    provider: Annotated[LLMProvider | None, Query()] = None,
    user_id: _UserIdFilter = None,
) -> SuccessResponse[AIAssistantMessageLogListResponse]:
    logs = await observability_service.get_message_logs(
        page=page, page_size=page_size, user_id=user_id, status=status, provider=provider
    )
    return SuccessResponse(message="OK", data=logs)
