"""create ai assistant permissions table

Revision ID: e5a9b8278172
Revises: 483997adb883
Create Date: 2026-08-28 10:28:54.376639

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a9b8278172"
down_revision: str | Sequence[str] | None = "483997adb883"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ai_assistant_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_messages_per_minute", sa.Integer(), nullable=True),
        sa.Column("max_messages_per_day", sa.Integer(), nullable=True),
        sa.Column("max_messages_per_month", sa.Integer(), nullable=True),
        sa.Column("max_new_chats_per_day", sa.Integer(), nullable=True),
        sa.Column("max_new_chats_per_month", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("ai_assistant_permissions")
