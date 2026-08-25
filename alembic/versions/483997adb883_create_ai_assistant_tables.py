"""create ai assistant tables

Revision ID: 483997adb883
Revises: 33c77536ae50
Create Date: 2026-08-24 13:05:32.682956

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "483997adb883"
down_revision: str | Sequence[str] | None = "33c77536ae50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "OLLAMA",
                "AWS_BEDROCK",
                "GROQ",
                "NVIDIA",
                "OPENAI",
                "HUGGINGFACE",
                "OPEN_ROUTER",
                name="llmprovider",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chats_user_id"), "chats", ["user_id"], unique=False)
    op.create_index("ix_chats_user_id_updated_at", "chats", ["user_id", "updated_at"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "USER",
                "ASSISTANT",
                "SYSTEM",
                "TOOL",
                name="chatmessagerole",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "sequence", name="uq_chat_messages_chat_id_sequence"),
    )
    op.create_index(op.f("ix_chat_messages_chat_id"), "chat_messages", ["chat_id"], unique=False)
    op.create_index(
        "ix_chat_messages_chat_id_sequence", "chat_messages", ["chat_id", "sequence"], unique=False
    )

    op.create_table(
        "chat_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "QUEUED",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="chatrunstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.Enum(
                "OLLAMA",
                "AWS_BEDROCK",
                "GROQ",
                "NVIDIA",
                "OPENAI",
                "HUGGINGFACE",
                "OPEN_ROUTER",
                name="llmprovider",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(op.f("ix_chat_runs_chat_id"), "chat_runs", ["chat_id"], unique=False)
    op.create_index(
        "ix_chat_runs_chat_id_created_at", "chat_runs", ["chat_id", "created_at"], unique=False
    )
    op.create_index("ix_chat_runs_status", "chat_runs", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_chat_runs_status", table_name="chat_runs")
    op.drop_index("ix_chat_runs_chat_id_created_at", table_name="chat_runs")
    op.drop_index(op.f("ix_chat_runs_chat_id"), table_name="chat_runs")
    op.drop_table("chat_runs")
    op.drop_index("ix_chat_messages_chat_id_sequence", table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_chat_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chats_user_id_updated_at", table_name="chats")
    op.drop_index(op.f("ix_chats_user_id"), table_name="chats")
    op.drop_table("chats")
