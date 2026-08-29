"""Business logic for AI assistant admin observability.

Mirrors `admin.service.AdminStatsService`'s approach: plain aggregate
queries directly against the ORM models, not through `ai_assistant.
repository`'s per-user-scoped repositories (which shouldn't grow
cross-user aggregate methods just for this).

Token/latency/tool-call/cost totals live inside `chat_runs.metadata`
(JSONB) or are derived from it (cost, via `observability.pricing`), none of
which can be summed portably in SQL across SQLite (the test suite) and
Postgres without dialect-specific JSON operators. Rather than branch on
dialect, the provider/timeseries/user breakdowns fetch only the narrow
columns they need (`created_at`, `status`, `provider`, `model`,
`extra_metadata`) for the matching rows and aggregate in Python — the same
"aggregate in Python over an already-filtered, bounded set of rows"
tradeoff `tools.analytics.get_largest_expenses` already makes. At today's
scale this is cheap; a materialized daily-rollup table would be the next
step if `chat_runs` ever grows large enough for this to matter.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.periods import start_of_month, start_of_week
from src.core.timezone import APP_TIMEZONE
from src.modules.ai_assistant.enums import ChatMessageRole, ChatRunStatus, LLMProvider
from src.modules.ai_assistant.models import AIAssistantPermission, Chat, ChatMessage, ChatRun
from src.modules.ai_assistant.observability.pricing import estimate_cost_usd
from src.modules.ai_assistant.observability.schemas import (
    AIAssistantOverview,
    AIAssistantProviderUsage,
    AIAssistantProviderUsageResponse,
    AIAssistantRunStatusCounts,
    AIAssistantUsageBucket,
    AIAssistantUsageTimeseries,
    AIAssistantUserUsage,
    AIAssistantUserUsageListResponse,
)
from src.modules.ai_assistant.tools.period_utils import resolve_range, to_utc_bounds
from src.modules.analytics.schemas import TrendInterval
from src.modules.recurring_expenses.enums import SortOrder
from src.modules.users.models import User

UserUsageSortField = Literal["messages_sent", "chats_created", "last_active"]

# One run's (status, provider, model, metadata), as fetched for Python-side
# aggregation — provider/model travel with every row (even inside a
# per-provider group, where they're redundant with the group key) so
# `_sum_metadata` has one uniform shape to work with everywhere it's used.
_RunEntry = tuple[ChatRunStatus, LLMProvider, str, dict[str, Any] | None]


@dataclass(frozen=True, slots=True)
class _MetadataTotals:
    input_tokens: int | None
    output_tokens: int | None
    tool_calls: int
    average_latency_ms: float | None
    estimated_cost_usd: Decimal | None


def _sum_metadata(rows: Sequence[_RunEntry]) -> _MetadataTotals:
    """Sums whichever of `input_tokens`/`output_tokens`/`tool_calls`/
    `latency_ms` each run actually reported (see `ChatRun.extra_metadata`,
    written by `ai_assistant.service._persist_run_outcome`), plus the
    estimated USD cost derivable from those tokens via `observability.
    pricing`. A token or cost figure stays `None` (never estimated) unless
    at least one run in the set reported/priced it — matches the "leave
    null if a provider doesn't report usage" rule the per-run metadata
    itself already follows.
    """
    input_tokens_sum = 0
    input_tokens_seen = False
    output_tokens_sum = 0
    output_tokens_seen = False
    tool_calls_sum = 0
    latency_values: list[float] = []
    cost_sum = Decimal(0)
    cost_seen = False

    for _status, provider, model, metadata in rows:
        if not metadata:
            continue
        input_tokens = metadata.get("input_tokens")
        if input_tokens is not None:
            input_tokens_sum += input_tokens
            input_tokens_seen = True
        output_tokens = metadata.get("output_tokens")
        if output_tokens is not None:
            output_tokens_sum += output_tokens
            output_tokens_seen = True
        tool_calls_sum += metadata.get("tool_calls") or 0
        latency_ms = metadata.get("latency_ms")
        if latency_ms is not None:
            latency_values.append(latency_ms)

        cost = estimate_cost_usd(
            provider, model, input_tokens=input_tokens, output_tokens=output_tokens
        )
        if cost is not None:
            cost_sum += cost
            cost_seen = True

    return _MetadataTotals(
        input_tokens=input_tokens_sum if input_tokens_seen else None,
        output_tokens=output_tokens_sum if output_tokens_seen else None,
        tool_calls=tool_calls_sum,
        average_latency_ms=(sum(latency_values) / len(latency_values) if latency_values else None),
        estimated_cost_usd=cost_sum if cost_seen else None,
    )


def _combine_costs(costs: Sequence[Decimal | None]) -> Decimal | None:
    """Sums a set of already-aggregated `estimated_cost_usd` figures with
    the same "null unless at least one is known" rule as `_sum_metadata`.
    """
    known = [cost for cost in costs if cost is not None]
    return sum(known, Decimal(0)) if known else None


def _chat_conditions(user_id: uuid.UUID | None) -> list[ColumnElement[bool]]:
    """The extra `WHERE` condition needed to scope a `Chat`-joined query to
    one user, or none at all when `user_id` is unset (system-wide).
    """
    return [Chat.user_id == user_id] if user_id is not None else []


def _local_date(dt: datetime) -> date:
    return dt.astimezone(APP_TIMEZONE).date()


def _bucket_start(interval: TrendInterval, day: date) -> date:
    if interval is TrendInterval.DAILY:
        return day
    local_dt = datetime(day.year, day.month, day.day, tzinfo=APP_TIMEZONE)
    if interval is TrendInterval.WEEKLY:
        return start_of_week(local_dt).date()
    if interval is TrendInterval.MONTHLY:
        return start_of_month(local_dt).date()
    return date(day.year, 1, 1)  # yearly


def _all_bucket_starts(interval: TrendInterval, start_date: date, end_date: date) -> list[date]:
    """Every distinct bucket start covering `[start_date, end_date]`, in
    chronological order, derived purely from calendar math — so a bucket
    with zero activity still appears (mirrors `analytics.service`'s
    trend-bucketing shape, reimplemented here rather than imported since
    that module's helpers are private and Decimal-money-shaped, not
    count/JSON-shaped).
    """
    starts: list[date] = []
    seen: set[date] = set()
    day = start_date
    while day <= end_date:
        bucket_start = _bucket_start(interval, day)
        if bucket_start not in seen:
            seen.add(bucket_start)
            starts.append(bucket_start)
        day += timedelta(days=1)
    return starts


def _format_period(interval: TrendInterval, bucket_start: date) -> tuple[str, date | None]:
    if interval is TrendInterval.DAILY:
        return bucket_start.isoformat(), None
    if interval is TrendInterval.WEEKLY:
        iso_year, iso_week, _ = bucket_start.isocalendar()
        return f"{iso_year}-W{iso_week:02d}", bucket_start + timedelta(days=6)
    if interval is TrendInterval.MONTHLY:
        return f"{bucket_start.year:04d}-{bucket_start.month:02d}", None
    return f"{bucket_start.year:04d}", None


class AIAssistantObservabilityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_overview(self, user_id: uuid.UUID | None = None) -> AIAssistantOverview:
        now = datetime.now(UTC)
        last_7_days = now - timedelta(days=7)
        last_30_days = now - timedelta(days=30)

        chat_conditions = _chat_conditions(user_id)
        message_conditions = [ChatMessage.role == ChatMessageRole.USER, *_chat_conditions(user_id)]
        run_conditions = list(_chat_conditions(user_id))
        permission_conditions = (
            [AIAssistantPermission.enabled.is_(True), AIAssistantPermission.user_id == user_id]
            if user_id is not None
            else [AIAssistantPermission.enabled.is_(True)]
        )

        total_chats = await self._session.scalar(
            select(func.count()).select_from(Chat).where(*chat_conditions)
        )
        total_messages_sent = await self._session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(*message_conditions)
        )
        total_runs = await self._session.scalar(
            select(func.count())
            .select_from(ChatRun)
            .join(Chat, Chat.id == ChatRun.chat_id)
            .where(*run_conditions)
        )

        status_rows = (
            await self._session.execute(
                select(ChatRun.status, func.count())
                .select_from(ChatRun)
                .join(Chat, Chat.id == ChatRun.chat_id)
                .where(*run_conditions)
                .group_by(ChatRun.status)
            )
        ).all()
        counts_by_status: dict[ChatRunStatus, int] = {}
        for status, count in status_rows:
            counts_by_status[status] = count
        runs_by_status = AIAssistantRunStatusCounts(
            queued=counts_by_status.get(ChatRunStatus.QUEUED, 0),
            running=counts_by_status.get(ChatRunStatus.RUNNING, 0),
            completed=counts_by_status.get(ChatRunStatus.COMPLETED, 0),
            failed=counts_by_status.get(ChatRunStatus.FAILED, 0),
            cancelled=counts_by_status.get(ChatRunStatus.CANCELLED, 0),
        )

        runs_7d = await self._session.scalar(
            select(func.count())
            .select_from(ChatRun)
            .join(Chat, Chat.id == ChatRun.chat_id)
            .where(ChatRun.created_at >= last_7_days, *run_conditions)
        )
        runs_30d = await self._session.scalar(
            select(func.count())
            .select_from(ChatRun)
            .join(Chat, Chat.id == ChatRun.chat_id)
            .where(ChatRun.created_at >= last_30_days, *run_conditions)
        )
        messages_7d = await self._session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(ChatMessage.created_at >= last_7_days, *message_conditions)
        )
        messages_30d = await self._session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(ChatMessage.created_at >= last_30_days, *message_conditions)
        )

        active_users_7d = await self._session.scalar(
            select(func.count(func.distinct(Chat.user_id)))
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(ChatMessage.created_at >= last_7_days, *message_conditions)
        )
        active_users_30d = await self._session.scalar(
            select(func.count(func.distinct(Chat.user_id)))
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(ChatMessage.created_at >= last_30_days, *message_conditions)
        )

        users_with_access_enabled = await self._session.scalar(
            select(func.count()).select_from(AIAssistantPermission).where(*permission_conditions)
        )

        run_metadata_rows = (
            await self._session.execute(
                select(ChatRun.status, ChatRun.provider, ChatRun.model, ChatRun.extra_metadata)
                .select_from(ChatRun)
                .join(Chat, Chat.id == ChatRun.chat_id)
                .where(*run_conditions)
            )
        ).all()
        all_entries: list[_RunEntry] = [
            (status, provider, model, metadata)
            for status, provider, model, metadata in run_metadata_rows
        ]
        totals = _sum_metadata(all_entries)

        return AIAssistantOverview(
            total_chats=total_chats or 0,
            total_messages_sent=total_messages_sent or 0,
            total_runs=total_runs or 0,
            runs_by_status=runs_by_status,
            runs_last_7_days=runs_7d or 0,
            runs_last_30_days=runs_30d or 0,
            messages_sent_last_7_days=messages_7d or 0,
            messages_sent_last_30_days=messages_30d or 0,
            active_users_last_7_days=active_users_7d or 0,
            active_users_last_30_days=active_users_30d or 0,
            users_with_access_enabled=users_with_access_enabled or 0,
            total_input_tokens=totals.input_tokens,
            total_output_tokens=totals.output_tokens,
            total_tool_calls=totals.tool_calls,
            average_latency_ms=totals.average_latency_ms,
            total_estimated_cost_usd=totals.estimated_cost_usd,
        )

    async def get_usage_timeseries(
        self,
        interval: TrendInterval,
        start_date: date | None,
        end_date: date | None,
        user_id: uuid.UUID | None = None,
    ) -> AIAssistantUsageTimeseries:
        resolved = resolve_range(start_date, end_date)
        start_utc, end_utc, _ = to_utc_bounds(resolved)
        chat_conditions = _chat_conditions(user_id)

        message_created_ats = (
            (
                await self._session.execute(
                    select(ChatMessage.created_at)
                    .select_from(ChatMessage)
                    .join(Chat, Chat.id == ChatMessage.chat_id)
                    .where(
                        ChatMessage.role == ChatMessageRole.USER,
                        ChatMessage.created_at >= start_utc,
                        ChatMessage.created_at < end_utc,
                        *chat_conditions,
                    )
                )
            )
            .scalars()
            .all()
        )
        run_rows = (
            await self._session.execute(
                select(
                    ChatRun.created_at,
                    ChatRun.status,
                    ChatRun.provider,
                    ChatRun.model,
                    ChatRun.extra_metadata,
                )
                .select_from(ChatRun)
                .join(Chat, Chat.id == ChatRun.chat_id)
                .where(
                    ChatRun.created_at >= start_utc, ChatRun.created_at < end_utc, *chat_conditions
                )
            )
        ).all()

        messages_by_bucket: dict[date, int] = defaultdict(int)
        for created_at in message_created_ats:
            messages_by_bucket[_bucket_start(interval, _local_date(created_at))] += 1

        runs_by_bucket: dict[date, list[_RunEntry]] = defaultdict(list)
        for created_at, status, provider, model, metadata in run_rows:
            runs_by_bucket[_bucket_start(interval, _local_date(created_at))].append(
                (status, provider, model, metadata)
            )

        data = []
        for bucket_start in _all_bucket_starts(interval, resolved.start_date, resolved.end_date):
            period, bucket_end = _format_period(interval, bucket_start)
            entries = runs_by_bucket.get(bucket_start, [])
            totals = _sum_metadata(entries)
            data.append(
                AIAssistantUsageBucket(
                    period=period,
                    start_date=bucket_start,
                    end_date=bucket_end,
                    messages_sent=messages_by_bucket.get(bucket_start, 0),
                    runs_completed=sum(
                        1 for status, *_ in entries if status is ChatRunStatus.COMPLETED
                    ),
                    runs_failed=sum(1 for status, *_ in entries if status is ChatRunStatus.FAILED),
                    runs_cancelled=sum(
                        1 for status, *_ in entries if status is ChatRunStatus.CANCELLED
                    ),
                    input_tokens=totals.input_tokens,
                    output_tokens=totals.output_tokens,
                    tool_calls=totals.tool_calls,
                    estimated_cost_usd=totals.estimated_cost_usd,
                )
            )

        return AIAssistantUsageTimeseries(
            interval=interval, start_date=resolved.start_date, end_date=resolved.end_date, data=data
        )

    async def get_provider_usage(
        self,
        start_date: date | None,
        end_date: date | None,
        user_id: uuid.UUID | None = None,
    ) -> AIAssistantProviderUsageResponse:
        resolved = resolve_range(start_date, end_date)
        start_utc, end_utc, _ = to_utc_bounds(resolved)

        rows = (
            await self._session.execute(
                select(ChatRun.provider, ChatRun.model, ChatRun.status, ChatRun.extra_metadata)
                .select_from(ChatRun)
                .join(Chat, Chat.id == ChatRun.chat_id)
                .where(
                    ChatRun.created_at >= start_utc,
                    ChatRun.created_at < end_utc,
                    *_chat_conditions(user_id),
                )
            )
        ).all()

        grouped: dict[tuple[LLMProvider, str], list[_RunEntry]] = defaultdict(list)
        for provider, model, status, metadata in rows:
            grouped[(provider, model)].append((status, provider, model, metadata))

        providers = []
        for (provider, model), entries in grouped.items():
            totals = _sum_metadata(entries)
            providers.append(
                AIAssistantProviderUsage(
                    provider=provider,
                    model=model,
                    total_runs=len(entries),
                    completed=sum(1 for status, *_ in entries if status is ChatRunStatus.COMPLETED),
                    failed=sum(1 for status, *_ in entries if status is ChatRunStatus.FAILED),
                    cancelled=sum(1 for status, *_ in entries if status is ChatRunStatus.CANCELLED),
                    input_tokens=totals.input_tokens,
                    output_tokens=totals.output_tokens,
                    tool_calls=totals.tool_calls,
                    average_latency_ms=totals.average_latency_ms,
                    estimated_cost_usd=totals.estimated_cost_usd,
                )
            )
        providers.sort(key=lambda p: p.total_runs, reverse=True)

        return AIAssistantProviderUsageResponse(
            start_date=resolved.start_date,
            end_date=resolved.end_date,
            total_estimated_cost_usd=_combine_costs([p.estimated_cost_usd for p in providers]),
            providers=providers,
        )

    async def get_user_usage(
        self,
        *,
        page: int,
        page_size: int,
        sort_by: UserUsageSortField,
        order: SortOrder,
        user_id: uuid.UUID | None = None,
    ) -> AIAssistantUserUsageListResponse:
        offset = (page - 1) * page_size
        thirty_days_ago = datetime.now(UTC) - timedelta(days=30)

        chat_count = (
            select(func.count())
            .select_from(Chat)
            .where(Chat.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )
        message_count = (
            select(func.count())
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(Chat.user_id == User.id, ChatMessage.role == ChatMessageRole.USER)
            .correlate(User)
            .scalar_subquery()
        )
        message_count_30d = (
            select(func.count())
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(
                Chat.user_id == User.id,
                ChatMessage.role == ChatMessageRole.USER,
                ChatMessage.created_at >= thirty_days_ago,
            )
            .correlate(User)
            .scalar_subquery()
        )
        last_active = (
            select(func.max(ChatMessage.created_at))
            .select_from(ChatMessage)
            .join(Chat, Chat.id == ChatMessage.chat_id)
            .where(Chat.user_id == User.id, ChatMessage.role == ChatMessageRole.USER)
            .correlate(User)
            .scalar_subquery()
        )
        enabled = (
            select(AIAssistantPermission.enabled)
            .where(AIAssistantPermission.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        )

        # Only users who have ever created a chat show up in this table —
        # everyone else has nothing to observe yet. `user_id`, when given,
        # narrows the table to that one user (present only if they qualify).
        row_conditions: list[ColumnElement[bool]] = [chat_count > 0]
        if user_id is not None:
            row_conditions.append(User.id == user_id)

        total = await self._session.scalar(
            select(func.count()).select_from(User).where(*row_conditions)
        )

        sort_column = {
            "messages_sent": message_count,
            "chats_created": chat_count,
            "last_active": last_active,
        }[sort_by]
        order_by = sort_column.desc() if order is SortOrder.DESC else sort_column.asc()

        rows = (
            await self._session.execute(
                select(
                    User.id,
                    User.username,
                    User.email,
                    func.coalesce(enabled, False),
                    chat_count,
                    message_count,
                    message_count_30d,
                    last_active,
                )
                .where(*row_conditions)
                .order_by(order_by, User.id)
                .offset(offset)
                .limit(page_size)
            )
        ).all()

        page_user_ids = [row[0] for row in rows]
        cost_by_user = await self._cost_by_user(page_user_ids)

        items = [
            AIAssistantUserUsage(
                user_id=user_id,
                username=username,
                email=email,
                enabled=bool(is_enabled),
                total_chats=chats,
                total_messages_sent=messages,
                messages_sent_last_30_days=messages_30d,
                last_active_at=last_active_at,
                estimated_cost_usd=cost_by_user.get(user_id),
            )
            for (
                user_id,
                username,
                email,
                is_enabled,
                chats,
                messages,
                messages_30d,
                last_active_at,
            ) in rows
        ]

        return AIAssistantUserUsageListResponse(
            items=items, total=total or 0, page=page, page_size=page_size
        )

    async def _cost_by_user(self, user_ids: Sequence[Any]) -> dict[Any, Decimal | None]:
        """Estimated all-time cost per user, for only the given `user_ids`
        (the current page) — computed separately from the paginated query
        above since cost aggregation is Python-side (see module docstring)
        and shouldn't run against every user just to page through 20.
        """
        if not user_ids:
            return {}

        rows = (
            await self._session.execute(
                select(
                    Chat.user_id,
                    ChatRun.status,
                    ChatRun.provider,
                    ChatRun.model,
                    ChatRun.extra_metadata,
                )
                .join(Chat, Chat.id == ChatRun.chat_id)
                .where(Chat.user_id.in_(user_ids))
            )
        ).all()

        entries_by_user: dict[Any, list[_RunEntry]] = defaultdict(list)
        for user_id, status, provider, model, metadata in rows:
            entries_by_user[user_id].append((status, provider, model, metadata))

        return {
            user_id: _sum_metadata(entries).estimated_cost_usd
            for user_id, entries in entries_by_user.items()
        }
