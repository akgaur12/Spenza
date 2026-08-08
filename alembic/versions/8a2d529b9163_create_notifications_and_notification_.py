"""create notifications and notification_preferences tables

Revision ID: 8a2d529b9163
Revises: 5d6b5c663cd7
Create Date: 2026-08-07 21:47:36.718573

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "8a2d529b9163"
down_revision: str | Sequence[str] | None = "5d6b5c663cd7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTIFICATION_TYPES = (
    "WELCOME",
    "REPORT_READY",
    "IMPORT_COMPLETED",
    "EXPORT_COMPLETED",
    "RECURRING_EXPENSE_CREATED",
    "PASSWORD_CHANGED",
    "SYSTEM",
    "AI_INSIGHT",
    "SECURITY_ALERT",
    "SUBSCRIPTION_EXPIRING",
    "BUDGET_ALERT",
    "WEEKLY_SUMMARY",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(*_NOTIFICATION_TYPES, name="notificationtype", native_enum=False, length=50),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum(
                "LOW",
                "NORMAL",
                "HIGH",
                "CRITICAL",
                name="notificationpriority",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_is_read"), "notifications", ["is_read"], unique=False)
    op.create_index(op.f("ix_notifications_type"), "notifications", ["type"], unique=False)
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index(
        "ix_notifications_user_id_created_at",
        "notifications",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_user_id_is_read", "notifications", ["user_id", "is_read"], unique=False
    )
    op.create_index(
        "ix_notifications_user_id_type", "notifications", ["user_id", "type"], unique=False
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "notification_type",
            sa.Enum(*_NOTIFICATION_TYPES, name="notificationtype", native_enum=False, length=50),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("delivery_time", sa.Time(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "notification_type", name="uq_notification_preferences_user_type"
        ),
    )
    op.create_index(
        op.f("ix_notification_preferences_user_id"),
        "notification_preferences",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_notification_preferences_user_id"), table_name="notification_preferences"
    )
    op.drop_table("notification_preferences")

    op.drop_index("ix_notifications_user_id_type", table_name="notifications")
    op.drop_index("ix_notifications_user_id_is_read", table_name="notifications")
    op.drop_index("ix_notifications_user_id_created_at", table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_type"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_is_read"), table_name="notifications")
    op.drop_table("notifications")
