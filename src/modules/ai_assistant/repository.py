"""Data-access layer for the `ai_assistant` module.

Repositories only translate between the ORM and plain Python — no business
rules, no HTTP concerns, no commits (the service decides when to commit;
see `ai_assistant.service` for why this module commits more eagerly than
the request-scoped default).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ai_assistant.enums import ChatMessageRole, ChatRunStatus, LLMProvider
from src.modules.ai_assistant.models import Chat, ChatMessage, ChatRun

# Roles surfaced to the frontend by `GET .../messages` — internal
# system/tool turns exist only for the agent's own context.
USER_FACING_ROLES = (ChatMessageRole.USER, ChatMessageRole.ASSISTANT)


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(self, *, user_id: uuid.UUID, title: str, provider: LLMProvider, model: str) -> Chat:
        chat = Chat(user_id=user_id, title=title, provider=provider, model=model)
        self._session.add(chat)
        return chat

    async def get_by_id_for_user(self, chat_id: uuid.UUID, user_id: uuid.UUID) -> Chat | None:
        result = await self._session.execute(
            select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[Chat, int]], int]:
        """Chats newest-updated-first, each paired with its user-facing
        message count (a scalar subquery, computed in SQL so pagination
        never has to fetch every message just to count them).
        """
        conditions = [Chat.user_id == user_id]
        if search:
            conditions.append(func.lower(Chat.title).like(f"%{search.lower()}%"))

        total = await self._session.scalar(
            select(func.count()).select_from(Chat).where(*conditions)
        )

        message_count = (
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.chat_id == Chat.id,
                ChatMessage.role.in_(USER_FACING_ROLES),
            )
            .correlate(Chat)
            .scalar_subquery()
        )
        result = await self._session.execute(
            select(Chat, message_count)
            .where(*conditions)
            .order_by(Chat.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = [(chat, count) for chat, count in result.all()]
        return rows, total or 0

    async def delete(self, chat: Chat) -> None:
        await self._session.delete(chat)

    async def flush(self) -> None:
        await self._session.flush()


class ChatMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_sequence(self, chat_id: uuid.UUID) -> int:
        current_max = await self._session.scalar(
            select(func.max(ChatMessage.sequence)).where(ChatMessage.chat_id == chat_id)
        )
        return (current_max or 0) + 1

    def create(
        self,
        *,
        chat_id: uuid.UUID,
        role: ChatMessageRole,
        content: str,
        sequence: int,
        extra_metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            chat_id=chat_id,
            role=role,
            content=content,
            sequence=sequence,
            extra_metadata=extra_metadata,
        )
        self._session.add(message)
        return message

    async def get_by_id_for_chat(
        self, message_id: uuid.UUID, chat_id: uuid.UUID
    ) -> ChatMessage | None:
        result = await self._session.execute(
            select(ChatMessage).where(ChatMessage.id == message_id, ChatMessage.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def list_for_chat(
        self,
        chat_id: uuid.UUID,
        *,
        offset: int,
        limit: int,
        roles: tuple[ChatMessageRole, ...] = USER_FACING_ROLES,
    ) -> tuple[list[ChatMessage], int]:
        conditions = [ChatMessage.chat_id == chat_id, ChatMessage.role.in_(roles)]
        total = await self._session.scalar(
            select(func.count()).select_from(ChatMessage).where(*conditions)
        )
        result = await self._session.execute(
            select(ChatMessage)
            .where(*conditions)
            .order_by(ChatMessage.sequence.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def list_recent_for_context(
        self,
        chat_id: uuid.UUID,
        *,
        limit: int,
        roles: tuple[ChatMessageRole, ...] = USER_FACING_ROLES,
    ) -> list[ChatMessage]:
        """The most recent `limit` messages, in chronological order — the
        agent's context window. See `AI_CONTEXT_WINDOW_MESSAGES`; this is
        the one place a future summarization/long-term-memory feature would
        change. `roles` defaults to user/assistant turns only — the system
        prompt is rebuilt fresh every run (see `agent.prompts`) rather than
        persisted, and nothing currently writes `system`/`tool` rows.
        """
        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_id == chat_id, ChatMessage.role.in_(roles))
            .order_by(ChatMessage.sequence.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def get_first_user_message(self, chat_id: uuid.UUID) -> ChatMessage | None:
        result = await self._session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_id == chat_id, ChatMessage.role == ChatMessageRole.USER)
            .order_by(ChatMessage.sequence.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def update_content(
        self, message: ChatMessage, *, content: str, extra_metadata: dict[str, Any] | None = None
    ) -> None:
        message.content = content
        if extra_metadata is not None:
            message.extra_metadata = extra_metadata

    async def flush(self) -> None:
        await self._session.flush()


class ChatRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(
        self,
        *,
        chat_id: uuid.UUID,
        message_id: uuid.UUID,
        provider: LLMProvider,
        model: str,
    ) -> ChatRun:
        run = ChatRun(
            chat_id=chat_id,
            message_id=message_id,
            provider=provider,
            model=model,
            status=ChatRunStatus.QUEUED,
        )
        self._session.add(run)
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> ChatRun | None:
        result = await self._session.execute(select(ChatRun).where(ChatRun.id == run_id))
        return result.scalar_one_or_none()

    async def get_by_message_id_for_user(
        self, message_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChatRun | None:
        result = await self._session.execute(
            select(ChatRun)
            .join(Chat, Chat.id == ChatRun.chat_id)
            .where(ChatRun.message_id == message_id, Chat.user_id == user_id)
        )
        return result.scalar_one_or_none()

    def mark_running(self, run: ChatRun, *, started_at: datetime) -> None:
        run.status = ChatRunStatus.RUNNING
        run.started_at = started_at

    def mark_completed(
        self, run: ChatRun, *, completed_at: datetime, extra_metadata: dict[str, Any] | None
    ) -> None:
        run.status = ChatRunStatus.COMPLETED
        run.completed_at = completed_at
        run.extra_metadata = extra_metadata

    def mark_failed(
        self,
        run: ChatRun,
        *,
        completed_at: datetime,
        error: str,
        extra_metadata: dict[str, Any] | None,
    ) -> None:
        run.status = ChatRunStatus.FAILED
        run.completed_at = completed_at
        run.error = error
        run.extra_metadata = extra_metadata

    def mark_cancelled(self, run: ChatRun, *, completed_at: datetime) -> None:
        run.status = ChatRunStatus.CANCELLED
        run.completed_at = completed_at

    async def flush(self) -> None:
        await self._session.flush()
