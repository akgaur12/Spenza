"""Pydantic v2 request/response schemas for the `notifications` module.

No creation schema — notifications are never created via the API (see the
module docstring in `service.py`); every request schema here is either a
preference update or a query-parameter shape.
"""

import uuid
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from src.modules.notifications.enums import NotificationPriority, NotificationType
from src.modules.notifications.models import Notification
from src.modules.notifications.preferences.service import ResolvedPreference
from src.modules.notifications.validators import validate_timezone

# ── Notifications ─────────────────────────────────────────────────────────


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    message: str
    payload: dict[str, Any]
    priority: NotificationPriority
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    page: int
    page_size: int
    total: int
    total_pages: int


class UnreadCountResponse(BaseModel):
    count: int


class MarkAllReadResponse(BaseModel):
    updated: int = 0


class TestEmailResponse(BaseModel):
    sent_to: str


def to_response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        type=notification.type,
        title=notification.title,
        message=notification.message,
        payload=notification.payload,
        priority=notification.priority,
        is_read=notification.is_read,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


# ── Preferences ───────────────────────────────────────────────────────────


class NotificationPreferenceUpdate(BaseModel):
    """All fields optional (`PATCH` semantics) — only the ones present are
    changed; anything left unset keeps its current value (or the default,
    for a type with no row yet — see `NotificationPreferenceService`).
    """

    enabled: bool | None = None
    in_app_enabled: bool | None = None
    email_enabled: bool | None = None
    delivery_time: time | None = None
    timezone: str | None = None

    model_config = ConfigDict(json_schema_extra={"example": {"email_enabled": True}})

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_timezone(value)


class NotificationPreferenceResponse(BaseModel):
    notification_type: NotificationType
    enabled: bool
    in_app_enabled: bool
    email_enabled: bool
    delivery_time: time | None
    timezone: str | None
    is_default: bool = False


class NotificationPreferenceListResponse(BaseModel):
    items: list[NotificationPreferenceResponse]


def preference_to_response(preference: ResolvedPreference) -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse(
        notification_type=preference.notification_type,
        enabled=preference.enabled,
        in_app_enabled=preference.in_app_enabled,
        email_enabled=preference.email_enabled,
        delivery_time=preference.delivery_time,
        timezone=preference.timezone,
        is_default=preference.is_default,
    )
