"""Enums for the `notifications` module.

String-backed columns (`Enum(PyEnum, native_enum=False, length=N)`), the
same convention `users.models.UserRole`/`OTPPurpose` and
`recurring_expenses.enums` already use — a plain `VARCHAR` under a native
Postgres `ENUM` type, so adding a new `NotificationType` member is a
Python-only change with no migration required, and the same model works
against both Postgres (production) and SQLite (the test suite).
"""

from enum import StrEnum


class NotificationType(StrEnum):
    """Deliberately open-ended — every module that wants to notify a user
    picks one of these (or `SYSTEM` as a catch-all) rather than inventing
    its own notification concept. Adding a member here is the only change
    needed to support a new kind of notification; no schema change, no new
    table, no new endpoint.
    """

    WELCOME = "welcome"
    REPORT_READY = "report_ready"
    IMPORT_COMPLETED = "import_completed"
    EXPORT_COMPLETED = "export_completed"
    RECURRING_EXPENSE_CREATED = "recurring_expense_created"
    PASSWORD_CHANGED = "password_changed"
    SYSTEM = "system"
    # Reserved for near-future modules — listed now so call sites and the
    # preferences UI can be designed against the full set without a second
    # migration when each one actually starts sending:
    AI_INSIGHT = "ai_insight"
    SECURITY_ALERT = "security_alert"
    SUBSCRIPTION_EXPIRING = "subscription_expiring"
    BUDGET_ALERT = "budget_alert"
    WEEKLY_SUMMARY = "weekly_summary"


class NotificationPriority(StrEnum):
    """Presentation only (e.g. sort order, badge color) — no delivery or
    business-logic behavior is keyed off priority in this phase.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DeliveryChannel(StrEnum):
    """Keys into `NotificationService`'s channel registry — one entry per
    `BaseNotificationChannel` implementation (see `delivery/`).
    """

    IN_APP = "in_app"
    EMAIL = "email"


class NotificationSortField(StrEnum):
    """Columns the list endpoint may sort by — see `NotificationRepository`."""

    CREATED_AT = "created_at"
    PRIORITY = "priority"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class DeliveryLogStatus(StrEnum):
    """A `notification_delivery_logs` row's outcome for one delivery attempt."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
