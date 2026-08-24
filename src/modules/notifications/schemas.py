"""Pydantic v2 request/response schemas for the `notifications` module.

No creation schema — notifications are never created via the API (see the
module docstring in `service.py`); every request schema here is either a
preference update or a query-parameter shape.
"""

import uuid
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.modules.notifications.enums import (
    DeliveryChannel,
    DeliveryLogStatus,
    NotificationPriority,
    NotificationType,
)
from src.modules.notifications.models import Notification, NotificationDeliveryLog
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


# ── Admin ─────────────────────────────────────────────────────────────────


class BroadcastNotificationRequest(BaseModel):
    """`user_ids` omitted (or empty) broadcasts to every active, verified
    user; otherwise only the listed users are targeted.
    """

    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=1000)
    notification_type: NotificationType = NotificationType.SYSTEM
    priority: NotificationPriority = NotificationPriority.NORMAL
    user_ids: list[uuid.UUID] | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Scheduled maintenance",
                "message": "Spenza will be briefly unavailable tonight at 11 PM IST.",
            }
        }
    )


class BroadcastNotificationResponse(BaseModel):
    targeted: int
    sent: int
    skipped: int


class DeliveryLogResponse(BaseModel):
    id: uuid.UUID
    notification_id: uuid.UUID | None
    channel: DeliveryChannel
    status: DeliveryLogStatus
    attempt: int
    provider: str | None
    error_message: str | None
    sent_at: datetime | None
    created_at: datetime


class DeliveryLogListResponse(BaseModel):
    items: list[DeliveryLogResponse]
    total: int
    page: int
    page_size: int


def delivery_log_to_response(log: NotificationDeliveryLog) -> DeliveryLogResponse:
    return DeliveryLogResponse(
        id=log.id,
        notification_id=log.notification_id,
        channel=log.channel,
        status=log.status,
        attempt=log.attempt,
        provider=log.provider,
        error_message=log.error_message,
        sent_at=log.sent_at,
        created_at=log.created_at,
    )


class EmailConfigResponse(BaseModel):
    """Current email delivery configuration. Secrets (`SENDER_PASSWORD`,
    `RESEND_API_KEY`, `MAILJET_API_SECRET`) are never included — only
    whether each HTTP-API backend has credentials configured at all.
    `sender_email` is whichever backend `EMAIL_BACKEND` currently selects.
    """

    backend: str
    sender_name: str
    sender_email: str | None
    smtp_server: str
    smtp_port: int
    smtp_use_tls: bool
    resend_configured: bool
    mailjet_configured: bool
    max_retries: int
    retry_base_delay_seconds: float


class SendAdminEmailRequest(BaseModel):
    """A custom, admin-composed email sent directly to one or more specific
    users — e.g. a support follow-up or a targeted announcement. Unlike
    `POST /admin/notifications/broadcast`, this always reaches every listed
    user regardless of their notification preferences (an admin explicitly
    naming these recipients is a stronger signal than a broadcast's
    respect-preferences default), and it isn't recorded as a `Notification`.
    """

    user_ids: list[uuid.UUID] = Field(..., min_length=1)
    subject: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1, max_length=5000)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_ids": ["5e2f3f3a-8b8a-4b1a-9a1a-6f6a1e2c9d10"],
                "subject": "Following up on your support request",
                "message": "Hi — the issue you reported has been fixed. Let us know if it recurs.",
            }
        }
    )


class SendAdminEmailResponse(BaseModel):
    targeted: int
    sent: int
    failed: int
    unknown_user_ids: list[uuid.UUID]
