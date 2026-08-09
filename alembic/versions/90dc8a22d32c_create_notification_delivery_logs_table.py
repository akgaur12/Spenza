"""create notification delivery logs table

Revision ID: 90dc8a22d32c
Revises: 8a2d529b9163
Create Date: 2026-08-07 22:37:07.147637

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "90dc8a22d32c"
down_revision: str | Sequence[str] | None = "8a2d529b9163"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_delivery_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=True),
        sa.Column(
            "channel",
            sa.Enum("IN_APP", "EMAIL", name="deliverychannel", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "SUCCESS",
                "FAILED",
                name="deliverylogstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notification_delivery_logs_created_at"),
        "notification_delivery_logs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_delivery_logs_notification_id"),
        "notification_delivery_logs",
        ["notification_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_delivery_logs_notification_id_channel",
        "notification_delivery_logs",
        ["notification_id", "channel"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_logs_notification_id_channel",
        table_name="notification_delivery_logs",
    )
    op.drop_index(
        op.f("ix_notification_delivery_logs_notification_id"),
        table_name="notification_delivery_logs",
    )
    op.drop_index(
        op.f("ix_notification_delivery_logs_created_at"), table_name="notification_delivery_logs"
    )
    op.drop_table("notification_delivery_logs")
