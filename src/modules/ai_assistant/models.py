"""ORM models for the `ai_assistant` module.

Three tables: `chats` (one row per conversation), `chat_messages` (every
user/assistant/system/tool turn in a chat, ordered by `sequence`), and
`chat_runs` (one row per agent execution — tracks status/timing/usage for
the assistant message it fills in).

`Base.metadata` is reserved by SQLAlchemy, so the spec's `metadata` JSONB
column on `chat_messages`/`chat_runs` is exposed as the Python attribute
`extra_metadata`, mapped to the physical column name `"metadata"` — the same
trick already used by `Notification.payload` in
`src.modules.notifications.models`.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.core.database import Base, TimestampMixin, UTCDateTime
from src.modules.ai_assistant.enums import ChatMessageRole, ChatRunStatus, LLMProvider

# Generic `JSON` everywhere except Postgres, where it renders as the real
# `JSONB` type — matches `notifications.models._JSONVariant` exactly, so no
# dialect-specific test setup is needed (SQLite has no native JSONB).
_JSONVariant = JSON().with_variant(JSONB(), "postgresql")

DEFAULT_CHAT_TITLE = "New Chat"


class Chat(TimestampMixin, Base):
    """A single conversation between a user and the AI assistant.

    `provider`/`model` are the *default* model configuration for future
    messages in this chat — they can be changed at any time (see
    `ChatService.update_for_user`) without rewriting past messages, since
    each `ChatRun` snapshots its own provider/model at the time it ran.
    """

    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_id_updated_at", "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default=DEFAULT_CHAT_TITLE)
    provider: Mapped[LLMProvider] = mapped_column(
        Enum(LLMProvider, native_enum=False, length=20), nullable=False
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)

    def __repr__(self) -> str:
        return f"Chat(id={self.id}, user_id={self.user_id}, title={self.title!r})"


class ChatMessage(TimestampMixin, Base):
    """One turn in a chat's history, in strict `sequence` order.

    `content` is the empty string for an assistant message created at run
    start and filled in as the stream progresses (see `ChatService`).
    System/tool messages are persisted for the agent's own context but are
    not returned to the frontend by `GET .../messages` (see `ai_assistant.
    schemas`) — only `user`/`assistant` rows are user-facing.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "sequence", name="uq_chat_messages_chat_id_sequence"),
        Index("ix_chat_messages_chat_id_sequence", "chat_id", "sequence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ChatMessageRole] = mapped_column(
        Enum(ChatMessageRole, native_enum=False, length=20), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", _JSONVariant, nullable=True
    )

    def __repr__(self) -> str:
        return f"ChatMessage(id={self.id}, chat_id={self.chat_id}, role={self.role})"


class ChatRun(TimestampMixin, Base):
    """One agent execution — created `queued`, transitions to `running`,
    then to exactly one terminal status. `message_id` points at the
    assistant `ChatMessage` this run produces (created empty, filled in as
    the run streams) — this is what the cancel endpoint's `{message_id}`
    path parameter refers to.
    """

    __tablename__ = "chat_runs"
    __table_args__ = (
        Index("ix_chat_runs_chat_id_created_at", "chat_id", "created_at"),
        Index("ix_chat_runs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[ChatRunStatus] = mapped_column(
        Enum(ChatRunStatus, native_enum=False, length=20),
        default=ChatRunStatus.QUEUED,
        nullable=False,
    )
    provider: Mapped[LLMProvider] = mapped_column(
        Enum(LLMProvider, native_enum=False, length=20), nullable=False
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", _JSONVariant, nullable=True
    )

    def __repr__(self) -> str:
        return f"ChatRun(id={self.id}, chat_id={self.chat_id}, status={self.status})"
