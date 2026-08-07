"""Enums for the `recurring_expenses` module.

Mirrors the existing `Enum(PyEnum, native_enum=False, length=N)` convention
used by `users.models.UserRole`/`OTPPurpose` — a portable, string-backed
column (not a native Postgres `ENUM` type) so the same model works against
both Postgres (production) and SQLite (the test suite).
"""

from enum import StrEnum


class Frequency(StrEnum):
    """How often a recurring expense generates an occurrence."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class GenerationMode(StrEnum):
    """What happens when a recurring expense comes due.

    `REMINDER` deliberately never creates an expense today — it exists so
    the schedule/next-run-date machinery is already in place for a future
    notification feature, without that feature needing any schema or
    scheduler changes when it lands.
    """

    AUTO = "auto"
    REMINDER = "reminder"


class RecurringExpenseStatus(StrEnum):
    """Lifecycle state of a recurring expense definition.

    ACTIVE     -> the scheduler processes it when due.
    PAUSED     -> the scheduler skips it; resumable back to ACTIVE.
    COMPLETED  -> its `end_date` has passed; system-set, not user-settable.
    CANCELLED  -> permanently disabled by the user; terminal, like COMPLETED.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RecurringExpenseSortField(StrEnum):
    """Columns the list endpoint may sort by — see `RecurringExpenseRepository`."""

    CREATED_AT = "created_at"
    NEXT_RUN_DATE = "next_run_date"
    AMOUNT = "amount"
    DESCRIPTION = "description"


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"
