"""Pydantic v2 response schemas for AI assistant admin observability.

Every `estimated_cost_usd` field follows the same "leave it null rather
than guess" rule as the token fields it's derived from (see
`observability.pricing`): `null` when no run in the set had *both* a
published price for its provider/model *and* reported token counts;
otherwise the sum of whichever runs did — a partial sum, not "no cost".
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from src.modules.ai_assistant.enums import ChatRunStatus, LLMProvider
from src.modules.analytics.schemas import TrendInterval

# ── Overview ──────────────────────────────────────────────────────────────


class AIAssistantRunStatusCounts(BaseModel):
    queued: int
    running: int
    completed: int
    failed: int
    cancelled: int


class AIAssistantOverview(BaseModel):
    total_chats: int
    total_messages_sent: int
    total_runs: int
    runs_by_status: AIAssistantRunStatusCounts
    runs_last_7_days: int
    runs_last_30_days: int
    messages_sent_last_7_days: int
    messages_sent_last_30_days: int
    active_users_last_7_days: int
    active_users_last_30_days: int
    users_with_access_enabled: int
    total_input_tokens: int | None
    total_output_tokens: int | None
    total_tool_calls: int
    average_latency_ms: float | None
    total_estimated_cost_usd: Decimal | None


# ── Usage over time ───────────────────────────────────────────────────────


class AIAssistantUsageBucket(BaseModel):
    period: str
    start_date: date
    end_date: date | None
    messages_sent: int
    runs_completed: int
    runs_failed: int
    runs_cancelled: int
    input_tokens: int | None
    output_tokens: int | None
    tool_calls: int
    estimated_cost_usd: Decimal | None


class AIAssistantUsageTimeseries(BaseModel):
    interval: TrendInterval
    start_date: date
    end_date: date
    data: list[AIAssistantUsageBucket]


# ── Provider / model breakdown ────────────────────────────────────────────


class AIAssistantProviderUsage(BaseModel):
    provider: LLMProvider
    model: str
    total_runs: int
    completed: int
    failed: int
    cancelled: int
    input_tokens: int | None
    output_tokens: int | None
    tool_calls: int
    average_latency_ms: float | None
    estimated_cost_usd: Decimal | None


class AIAssistantProviderUsageResponse(BaseModel):
    start_date: date
    end_date: date
    total_estimated_cost_usd: Decimal | None
    providers: list[AIAssistantProviderUsage]


# ── Per-user usage ────────────────────────────────────────────────────────


class AIAssistantUserUsage(BaseModel):
    user_id: uuid.UUID
    username: str
    email: str
    enabled: bool
    total_chats: int
    total_messages_sent: int
    messages_sent_last_30_days: int
    last_active_at: datetime | None
    estimated_cost_usd: Decimal | None


class AIAssistantUserUsageListResponse(BaseModel):
    items: list[AIAssistantUserUsage]
    total: int
    page: int
    page_size: int


# ── Per-message logs ──────────────────────────────────────────────────────


class AIAssistantMessageLog(BaseModel):
    """One agent run (one user message -> one assistant reply), for the
    admin log table: who sent it, what went in and came out, and its
    token/cost/latency figures.
    """

    run_id: uuid.UUID
    chat_id: uuid.UUID
    user_id: uuid.UUID
    username: str
    email: str
    provider: LLMProvider
    model: str
    status: ChatRunStatus
    input_message: str | None
    output_message: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    tool_calls: int
    latency_ms: float | None
    estimated_cost_usd: Decimal | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class AIAssistantMessageLogListResponse(BaseModel):
    items: list[AIAssistantMessageLog]
    total: int
    page: int
    page_size: int
