"""ORM models for the `notifications` module.

Two tables: `notifications` (one row per notification ever generated for a
user — immutable except for `is_read`/`read_at`) and
`notification_preferences` (at most one row per `(user_id,
notification_type)` pair — see that model's docstring for what a missing
row means).
"""

import uuid
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.core.database import Base, TimestampMixin, UTCDateTime
from src.modules.notifications.enums import (
    DeliveryChannel,
    DeliveryLogStatus,
    NotificationPriority,
    NotificationType,
)

# Generic `JSON` everywhere except Postgres, where it renders as the real
# `JSONB` type the task asks for — `JSON` alone works unchanged against the
# test suite's SQLite database (which has no native JSONB), so no
# dialect-specific test setup is needed.
_JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Notification(Base):
    """A single notification generated for a user by `NotificationService`.

    No `updated_at`: a notification's content never changes after
    creation, only its read state (`is_read`/`read_at`), which are already
    explicit columns.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        Index("ix_notifications_user_id_is_read", "user_id", "is_read"),
        Index("ix_notifications_user_id_type", "user_id", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, length=50), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Notification-specific data (e.g. `{"report_type": "monthly", ...}`) —
    # deliberately untyped at the schema level so a new notification type
    # never needs a migration to carry its own shape of data.
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONVariant, nullable=False, default=dict)
    priority: Mapped[NotificationPriority] = mapped_column(
        Enum(NotificationPriority, native_enum=False, length=20),
        default=NotificationPriority.NORMAL,
        nullable=False,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(UTC), nullable=False
    )

    def __repr__(self) -> str:
        return f"Notification(id={self.id}, user_id={self.user_id}, type={self.type})"


class NotificationPreference(TimestampMixin, Base):
    """A user's delivery preferences for one `NotificationType`.

    No row for a given `(user_id, notification_type)` pair means "use the
    default" (enabled, in-app on, email off) — see
    `preferences.service.NotificationPreferenceService` for where that
    default lives. A row only exists once a user has actually changed
    something, so most users never accumulate one row per type.
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "notification_type", name="uq_notification_preferences_user_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, length=50), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Both nullable, both unused until Phase 11B's scheduled digest
    # delivery reads them — stored now so that phase needs no schema change.
    delivery_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return (
            f"NotificationPreference(user_id={self.user_id}, "
            f"notification_type={self.notification_type})"
        )


class NotificationDeliveryLog(Base):
    """One row per delivery *attempt* (not per notification) — a
    notification retried twice before succeeding has two rows here, so the
    table is a full audit trail for debugging delivery issues, not just a
    final-state cache.

    `notification_id` is nullable: `POST /notifications/test-email` sends
    without ever creating a `Notification` row, but still logs its attempt
    here for the same debuggability.
    """

    __tablename__ = "notification_delivery_logs"
    __table_args__ = (
        Index(
            "ix_notification_delivery_logs_notification_id_channel",
            "notification_id",
            "channel",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    channel: Mapped[DeliveryChannel] = mapped_column(
        Enum(DeliveryChannel, native_enum=False, length=20), nullable=False
    )
    status: Mapped[DeliveryLogStatus] = mapped_column(
        Enum(DeliveryLogStatus, native_enum=False, length=20), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return (
            f"NotificationDeliveryLog(notification_id={self.notification_id}, "
            f"channel={self.channel}, status={self.status}, attempt={self.attempt})"
        )
