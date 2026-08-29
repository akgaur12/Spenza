"""add observability indexes to chat runs and messages

Revision ID: f3b09a730623
Revises: e5a9b8278172
Create Date: 2026-08-28 13:32:55.193416

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b09a730623"
down_revision: str | Sequence[str] | None = "e5a9b8278172"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_chat_messages_role_created_at", "chat_messages", ["role", "created_at"], unique=False
    )
    op.create_index("ix_chat_runs_created_at", "chat_runs", ["created_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_chat_runs_created_at", table_name="chat_runs")
    op.drop_index("ix_chat_messages_role_created_at", table_name="chat_messages")
