"""Business logic for AI assistant per-user access control and usage
limits.

The one rule this module owns: what "no permission row yet" means — opt-in
access, i.e. `enabled=False` and every limit unset (see `_resolve`). Also
owns how "current usage" is measured: `chat_messages`/`chats` are queried
directly (via the existing `ai_assistant.repository` repositories) rather
than maintained via a separate counter table, since both are cheap,
indexed, point-in-time counts.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.logger import get_logger
from src.core.periods import start_of_day, start_of_month
from src.core.timezone import APP_TIMEZONE
from src.modules.ai_assistant.exceptions import (
    AIAssistantDisabledError,
    AIChatDailyChatLimitExceededError,
    AIChatDailyLimitExceededError,
    AIChatMonthlyChatLimitExceededError,
    AIChatMonthlyLimitExceededError,
    AIChatRateLimitedError,
)
from src.modules.ai_assistant.models import AIAssistantPermission
from src.modules.ai_assistant.permissions.repository import AIAssistantPermissionRepository
from src.modules.ai_assistant.permissions.schemas import (
    AIAssistantMeStatus,
    AIAssistantPermissionResponse,
    AIAssistantUsage,
)
from src.modules.ai_assistant.repository import ChatMessageRepository, ChatRepository
from src.modules.users.models import User

logger = get_logger(__name__)

_DEFAULT_ENABLED = False


@dataclass(frozen=True, slots=True)
class ResolvedPermission:
    """A permission with the "no row" default already merged in — callers
    never need to know whether it came from a real row or a fallback.
    """

    enabled: bool
    max_messages_per_minute: int | None
    max_messages_per_day: int | None
    max_messages_per_month: int | None
    max_new_chats_per_day: int | None
    max_new_chats_per_month: int | None


def _resolve(row: AIAssistantPermission | None) -> ResolvedPermission:
    if row is None:
        return ResolvedPermission(
            enabled=_DEFAULT_ENABLED,
            max_messages_per_minute=None,
            max_messages_per_day=None,
            max_messages_per_month=None,
            max_new_chats_per_day=None,
            max_new_chats_per_month=None,
        )
    return ResolvedPermission(
        enabled=row.enabled,
        max_messages_per_minute=row.max_messages_per_minute,
        max_messages_per_day=row.max_messages_per_day,
        max_messages_per_month=row.max_messages_per_month,
        max_new_chats_per_day=row.max_new_chats_per_day,
        max_new_chats_per_month=row.max_new_chats_per_month,
    )


def _day_start_utc() -> datetime:
    return start_of_day(datetime.now(APP_TIMEZONE)).astimezone(UTC)


def _month_start_utc() -> datetime:
    return start_of_month(datetime.now(APP_TIMEZONE)).astimezone(UTC)


class AIAssistantPermissionService:
    def __init__(self, session: AsyncSession) -> None:
        self._permissions = AIAssistantPermissionRepository(session)
        self._chats = ChatRepository(session)
        self._messages = ChatMessageRepository(session)

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_resolved(self, user_id: uuid.UUID) -> ResolvedPermission:
        row = await self._permissions.get_by_user_id(user_id)
        return _resolve(row)

    async def get_usage(self, user_id: uuid.UUID) -> AIAssistantUsage:
        day_start = _day_start_utc()
        month_start = _month_start_utc()
        return AIAssistantUsage(
            messages_sent_today=await self._messages.count_user_messages_since(user_id, day_start),
            messages_sent_this_month=await self._messages.count_user_messages_since(
                user_id, month_start
            ),
            chats_created_today=await self._chats.count_created_since(user_id, day_start),
            chats_created_this_month=await self._chats.count_created_since(user_id, month_start),
        )

    async def get_admin_view(self, user_id: uuid.UUID) -> AIAssistantPermissionResponse:
        resolved = await self.get_resolved(user_id)
        usage = await self.get_usage(user_id)
        return AIAssistantPermissionResponse(
            enabled=resolved.enabled,
            max_messages_per_minute=resolved.max_messages_per_minute,
            max_messages_per_day=resolved.max_messages_per_day,
            max_messages_per_month=resolved.max_messages_per_month,
            max_new_chats_per_day=resolved.max_new_chats_per_day,
            max_new_chats_per_month=resolved.max_new_chats_per_month,
            **usage.model_dump(),
        )

    async def get_me_status(self, user_id: uuid.UUID) -> AIAssistantMeStatus:
        resolved = await self.get_resolved(user_id)
        usage = await self.get_usage(user_id)
        return AIAssistantMeStatus(
            enabled=resolved.enabled,
            max_messages_per_day=resolved.max_messages_per_day,
            max_messages_per_month=resolved.max_messages_per_month,
            max_new_chats_per_day=resolved.max_new_chats_per_day,
            max_new_chats_per_month=resolved.max_new_chats_per_month,
            **usage.model_dump(),
        )

    # ── Admin write ───────────────────────────────────────────────────────

    async def update_for_user(
        self, user_id: uuid.UUID, updates: dict[str, object]
    ) -> AIAssistantPermissionResponse:
        """Upserts: `updates` is a request schema's `model_dump(exclude_
        unset=True)` — only fields the caller actually sent. The first
        change for a user creates their row, seeded from the model's own
        defaults for every field this call didn't touch; later changes
        just update the existing row. A limit sent as explicit `null` is
        honored (sets that limit to unlimited) since `exclude_unset`
        already distinguishes "sent as null" from "not sent" upstream.
        """
        row = await self._permissions.get_by_user_id(user_id)
        if row is None:
            row = self._permissions.create(user_id=user_id)
        for field, value in updates.items():
            setattr(row, field, value)

        await self._permissions.flush()
        logger.info("ai_assistant.permission.updated", user_id=str(user_id), **updates)
        return await self.get_admin_view(user_id)

    # ── Enforcement ───────────────────────────────────────────────────────
    # Called from `ai_assistant.service.ChatService` before creating a new
    # chat / persisting a new message — never from the router directly, so
    # the business rule lives in exactly one place.

    async def check_can_create_chat(self, user: User) -> None:
        resolved = await self.get_resolved(user.id)
        if not resolved.enabled:
            raise AIAssistantDisabledError()

        if resolved.max_new_chats_per_day is not None:
            count = await self._chats.count_created_since(user.id, _day_start_utc())
            if count >= resolved.max_new_chats_per_day:
                raise AIChatDailyChatLimitExceededError()

        if resolved.max_new_chats_per_month is not None:
            count = await self._chats.count_created_since(user.id, _month_start_utc())
            if count >= resolved.max_new_chats_per_month:
                raise AIChatMonthlyChatLimitExceededError()

    async def check_can_send_message(self, user: User) -> None:
        resolved = await self.get_resolved(user.id)
        if not resolved.enabled:
            raise AIAssistantDisabledError()

        # `max_messages_per_minute` is the one limit that isn't
        # "None = unlimited" — an unset per-user override falls back to
        # the global default rather than lifting the limit entirely.
        per_minute_limit = resolved.max_messages_per_minute
        if per_minute_limit is None:
            per_minute_limit = settings.AI_CHAT_REQUESTS_PER_MINUTE
        if per_minute_limit is not None:
            since = datetime.now(UTC) - timedelta(minutes=1)
            count = await self._messages.count_user_messages_since(user.id, since)
            if count >= per_minute_limit:
                raise AIChatRateLimitedError()

        if resolved.max_messages_per_day is not None:
            count = await self._messages.count_user_messages_since(user.id, _day_start_utc())
            if count >= resolved.max_messages_per_day:
                raise AIChatDailyLimitExceededError()

        if resolved.max_messages_per_month is not None:
            count = await self._messages.count_user_messages_since(user.id, _month_start_utc())
            if count >= resolved.max_messages_per_month:
                raise AIChatMonthlyLimitExceededError()
