"""create recurring_expenses table

Revision ID: 5d6b5c663cd7
Revises: 8ccf9e86f4dd
Create Date: 2026-08-07 20:54:37.758770

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5d6b5c663cd7"
down_revision: str | Sequence[str] | None = "8ccf9e86f4dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "recurring_expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum(
                "DAILY",
                "WEEKLY",
                "MONTHLY",
                "QUARTERLY",
                "YEARLY",
                name="frequency",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "generation_mode",
            sa.Enum("AUTO", "REMINDER", name="generationmode", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "PAUSED",
                "COMPLETED",
                "CANCELLED",
                name="recurringexpensestatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("next_run_date", sa.Date(), nullable=False),
        sa.Column("last_run_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_recurring_expenses_amount_positive"),
        sa.CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_recurring_expenses_end_date_after_start",
        ),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recurring_expenses_category_id"),
        "recurring_expenses",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_recurring_expenses_status_next_run_date",
        "recurring_expenses",
        ["status", "next_run_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recurring_expenses_user_id"), "recurring_expenses", ["user_id"], unique=False
    )
    op.create_index(
        "ix_recurring_expenses_user_id_status",
        "recurring_expenses",
        ["user_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_recurring_expenses_user_id_status", table_name="recurring_expenses")
    op.drop_index(op.f("ix_recurring_expenses_user_id"), table_name="recurring_expenses")
    op.drop_index("ix_recurring_expenses_status_next_run_date", table_name="recurring_expenses")
    op.drop_index(op.f("ix_recurring_expenses_category_id"), table_name="recurring_expenses")
    op.drop_table("recurring_expenses")
