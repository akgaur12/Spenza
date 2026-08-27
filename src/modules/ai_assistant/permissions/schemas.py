"""Pydantic v2 request/response schemas for AI assistant permissions."""

from pydantic import BaseModel, ConfigDict, Field

# ── Requests ────────────────────────────────────────────────────────────────


class AIAssistantPermissionUpdate(BaseModel):
    """All fields optional (`PATCH` semantics) — only fields actually sent
    are applied (see `model_dump(exclude_unset=True)` in the router). A
    limit field sent as explicit `null` sets that limit to unlimited;
    omitting it entirely leaves the existing value untouched.
    """

    enabled: bool | None = None
    max_messages_per_minute: int | None = Field(default=None, ge=0)
    max_messages_per_day: int | None = Field(default=None, ge=0)
    max_messages_per_month: int | None = Field(default=None, ge=0)
    max_new_chats_per_day: int | None = Field(default=None, ge=0)
    max_new_chats_per_month: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enabled": True,
                "max_messages_per_minute": 5,
                "max_messages_per_day": 100,
                "max_messages_per_month": 2000,
                "max_new_chats_per_day": 10,
                "max_new_chats_per_month": 100,
            }
        }
    )


# ── Responses ───────────────────────────────────────────────────────────────


class AIAssistantUsage(BaseModel):
    messages_sent_today: int
    messages_sent_this_month: int
    chats_created_today: int
    chats_created_this_month: int


class AIAssistantPermissionResponse(AIAssistantUsage):
    """Admin-facing view: every configured limit (including the per-minute
    one, which end users never see — see `AIAssistantMeStatus`) plus
    current usage.
    """

    enabled: bool
    max_messages_per_minute: int | None
    max_messages_per_day: int | None
    max_messages_per_month: int | None
    max_new_chats_per_day: int | None
    max_new_chats_per_month: int | None


class AIAssistantMeStatus(AIAssistantUsage):
    """The subset of a user's own AI assistant status exposed via
    `GET /api/users/me`, so a frontend can gate its UI (hide the entry
    point, show remaining quota) without a dedicated call. Deliberately
    omits `max_messages_per_minute` — a per-minute figure isn't meaningful
    to surface in a profile-style UI.
    """

    enabled: bool
    max_messages_per_day: int | None
    max_messages_per_month: int | None
    max_new_chats_per_day: int | None
    max_new_chats_per_month: int | None
