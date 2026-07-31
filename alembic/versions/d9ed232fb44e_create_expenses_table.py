"""create expenses table

Revision ID: d9ed232fb44e
Revises: c4abe0878b9f
Create Date: 2026-07-31 13:49:54.129670

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9ed232fb44e"
down_revision: str | Sequence[str] | None = "c4abe0878b9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("spent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_expenses_amount_positive"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_expenses_category_id"), "expenses", ["category_id"], unique=False)
    op.create_index(op.f("ix_expenses_user_id"), "expenses", ["user_id"], unique=False)
    op.create_index(
        "ix_expenses_user_id_category_id", "expenses", ["user_id", "category_id"], unique=False
    )
    op.create_index(
        "ix_expenses_user_id_spent_at", "expenses", ["user_id", "spent_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_expenses_user_id_spent_at", table_name="expenses")
    op.drop_index("ix_expenses_user_id_category_id", table_name="expenses")
    op.drop_index(op.f("ix_expenses_user_id"), table_name="expenses")
    op.drop_index(op.f("ix_expenses_category_id"), table_name="expenses")
    op.drop_table("expenses")
