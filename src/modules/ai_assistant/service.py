"""Business logic for the `ai_assistant` module.

`ChatService` owns chat/message CRUD and orchestrates one send-message run
in two steps:

1. `prepare_run()` — ownership + provider/model validation, persists the
   user message, an empty assistant message, and a `queued` run, with an
   **explicit commit** right there (see `stream_run`'s docstring for why
   this module commits more eagerly than the request-scoped default).
2. `stream_run()` — builds the tool registry + LangChain messages, drives
   `AgentRunner`, forwards its SSE events, and persists the terminal
   outcome in a `finally` so a run can never get stuck `running` — even if
   the client disconnects mid-stream.

The router calls these as two separate steps so a provider/model
validation failure in step 1 is a normal pre-stream HTTP error, not
something that has to be smuggled into the SSE protocol.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.app_config import settings
from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.modules.ai_assistant.agent.prompts import build_system_message, build_title_system_message
from src.modules.ai_assistant.agent.runner import AgentRunner, AgentRunResult, run_registry
from src.modules.ai_assistant.enums import ChatMessageRole, ChatRunStatus
from src.modules.ai_assistant.exceptions import (
    ChatNotFoundError,
    MessageNotFoundError,
    RunNotCancellableError,
)
from src.modules.ai_assistant.models import DEFAULT_CHAT_TITLE, Chat, ChatMessage, ChatRun
from src.modules.ai_assistant.permissions.service import AIAssistantPermissionService
from src.modules.ai_assistant.providers.factory import LLMFactory
from src.modules.ai_assistant.repository import (
    ChatMessageRepository,
    ChatRepository,
    ChatRunRepository,
)
from src.modules.ai_assistant.schemas import ChatCreate, ChatUpdate, MessageCreate
from src.modules.ai_assistant.streaming.events import SSEEvent
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.registry import build_tool_registry
from src.modules.ai_assistant.validators import MAX_TITLE_LENGTH
from src.modules.users.models import User

logger = get_logger(__name__)

# Holds references to fire-and-forget title-generation tasks so they can't
# be garbage-collected mid-execution (a documented asyncio pitfall).
_background_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True, slots=True)
class PreparedRun:
    chat: Chat
    user_message: ChatMessage
    assistant_message: ChatMessage
    run: ChatRun


def _to_lc_message(message: ChatMessage) -> BaseMessage:
    if message.role is ChatMessageRole.ASSISTANT:
        return AIMessage(content=message.content)
    return HumanMessage(content=message.content)


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._chats = ChatRepository(session)
        self._messages = ChatMessageRepository(session)
        self._runs = ChatRunRepository(session)
        self._permissions = AIAssistantPermissionService(session)

    # ── Chat CRUD ─────────────────────────────────────────────────────────

    async def create_for_user(self, user: User, data: ChatCreate) -> Chat:
        await self._permissions.check_can_create_chat(user)

        provider = data.provider or settings.AI_DEFAULT_PROVIDER
        model = data.model or settings.AI_DEFAULT_MODEL
        chat = self._chats.create(
            user_id=user.id, title=data.title or DEFAULT_CHAT_TITLE, provider=provider, model=model
        )
        await self._chats.flush()
        await self._session.commit()
        logger.info("ai.chat.created", chat_id=str(chat.id), user_id=str(user.id))
        return chat

    async def list_for_user(
        self, user: User, *, search: str | None, page: int, page_size: int
    ) -> tuple[list[tuple[Chat, int]], int]:
        offset = (page - 1) * page_size
        return await self._chats.list_for_user(
            user.id, search=search, offset=offset, limit=page_size
        )

    async def get_for_user(self, chat_id: uuid.UUID, user: User) -> Chat:
        chat = await self._chats.get_by_id_for_user(chat_id, user.id)
        if chat is None:
            raise ChatNotFoundError()
        return chat

    async def rename_for_user(self, chat_id: uuid.UUID, user: User, data: ChatUpdate) -> Chat:
        chat = await self.get_for_user(chat_id, user)
        chat.title = data.title
        await self._chats.flush()
        await self._session.commit()
        logger.info("ai.chat.renamed", chat_id=str(chat.id), user_id=str(user.id))
        return chat

    async def delete_for_user(self, chat_id: uuid.UUID, user: User) -> None:
        chat = await self.get_for_user(chat_id, user)
        await self._chats.delete(chat)
        await self._chats.flush()
        await self._session.commit()
        logger.info("ai.chat.deleted", chat_id=str(chat_id), user_id=str(user.id))

    # ── Messages ──────────────────────────────────────────────────────────

    async def list_messages(
        self, chat_id: uuid.UUID, user: User, *, page: int, page_size: int
    ) -> tuple[list[ChatMessage], int]:
        await self.get_for_user(chat_id, user)
        offset = (page - 1) * page_size
        return await self._messages.list_for_chat(chat_id, offset=offset, limit=page_size)

    # ── Send message / run lifecycle ─────────────────────────────────────

    async def prepare_run(self, chat_id: uuid.UUID, user: User, data: MessageCreate) -> PreparedRun:
        chat = await self.get_for_user(chat_id, user)
        await self._permissions.check_can_send_message(user)

        # Fail fast, before any SSE bytes are sent: an unconfigured
        # provider or an unsupported model surfaces as a normal HTTP error
        # here, not smuggled into the SSE protocol as a `run_failed` event.
        LLMFactory.create(chat.provider, chat.model, tools=[])

        user_sequence = await self._messages.next_sequence(chat_id)
        user_message = self._messages.create(
            chat_id=chat_id, role=ChatMessageRole.USER, content=data.message, sequence=user_sequence
        )
        await self._messages.flush()

        assistant_sequence = await self._messages.next_sequence(chat_id)
        assistant_message = self._messages.create(
            chat_id=chat_id, role=ChatMessageRole.ASSISTANT, content="", sequence=assistant_sequence
        )
        await self._messages.flush()

        run = self._runs.create(
            chat_id=chat_id,
            message_id=assistant_message.id,
            provider=chat.provider,
            model=chat.model,
        )
        await self._runs.flush()
        await self._session.commit()

        return PreparedRun(
            chat=chat, user_message=user_message, assistant_message=assistant_message, run=run
        )

    async def stream_run(self, prepared: PreparedRun, user: User) -> AsyncIterator[SSEEvent]:
        chat, run, assistant_message = prepared.chat, prepared.run, prepared.assistant_message

        tool_ctx = ToolContext(user=user, session=self._session)
        tools = build_tool_registry(tool_ctx)
        model, _capabilities = LLMFactory.create(chat.provider, chat.model, tools=tools)

        history_rows = await self._messages.list_recent_for_context(
            chat.id, limit=settings.AI_CONTEXT_WINDOW_MESSAGES
        )
        lc_messages: list[BaseMessage] = [
            build_system_message(),
            *(_to_lc_message(row) for row in history_rows),
        ]

        self._runs.mark_running(run, started_at=datetime.now(UTC))
        await self._runs.flush()
        await self._session.commit()

        runner = AgentRunner(
            agent_timeout_seconds=settings.AI_AGENT_TIMEOUT_SECONDS,
            tool_timeout_seconds=settings.AI_TOOL_TIMEOUT_SECONDS,
        )
        result_box: list[AgentRunResult] = []

        try:
            async for event in runner.stream(
                run_id=run.id,
                chat_id=chat.id,
                message_id=assistant_message.id,
                user_id=user.id,
                provider=chat.provider.value,
                model_name=chat.model,
                model=model,
                tools=tools,
                messages=lc_messages,
                result_box=result_box,
            ):
                yield event
        finally:
            await self._persist_run_outcome(chat, run, assistant_message, result_box)

    async def _persist_run_outcome(
        self,
        chat: Chat,
        run: ChatRun,
        assistant_message: ChatMessage,
        result_box: list[AgentRunResult],
    ) -> None:
        completed_at = datetime.now(UTC)

        if not result_box:
            # The generator was closed from outside (client disconnected,
            # server shutting down, ...) before reaching a terminal event —
            # never leave the run stuck `running`.
            self._runs.mark_cancelled(run, completed_at=completed_at)
            await self._runs.flush()
            await self._session.commit()
            return

        result = result_box[0]
        self._messages.update_content(assistant_message, content=result.content)

        latency_ms = (
            round((completed_at - run.started_at).total_seconds() * 1000)
            if run.started_at is not None
            else None
        )
        metadata = {
            "provider": chat.provider.value,
            "model": chat.model,
            "latency_ms": latency_ms,
            "input_tokens": result.metadata.input_tokens,
            "output_tokens": result.metadata.output_tokens,
            "tool_calls": result.metadata.tool_calls,
        }
        if result.status == "completed":
            self._runs.mark_completed(run, completed_at=completed_at, extra_metadata=metadata)
        elif result.status == "cancelled":
            self._runs.mark_cancelled(run, completed_at=completed_at)
        else:
            self._runs.mark_failed(
                run,
                completed_at=completed_at,
                error=result.error or "Unknown error",
                extra_metadata=metadata,
            )
        await self._messages.flush()
        await self._runs.flush()
        await self._session.commit()

        logger.info(
            "ai.run.finished",
            chat_id=str(chat.id),
            run_id=str(run.id),
            provider=chat.provider.value,
            model=chat.model,
            status=result.status,
            latency_ms=latency_ms,
            tool_calls=result.metadata.tool_calls,
            input_tokens=result.metadata.input_tokens,
            output_tokens=result.metadata.output_tokens,
            error=result.error,
        )

        if (
            result.status == "completed"
            and chat.title == DEFAULT_CHAT_TITLE
            and settings.AI_TITLE_GENERATION_ENABLED
        ):
            _spawn_title_generation(chat.id)

    async def cancel_run(self, chat_id: uuid.UUID, message_id: uuid.UUID, user: User) -> None:
        await self.get_for_user(chat_id, user)
        run = await self._runs.get_by_message_id_for_user(message_id, user.id)
        if run is None:
            raise MessageNotFoundError()
        if run.status not in (ChatRunStatus.QUEUED, ChatRunStatus.RUNNING):
            raise RunNotCancellableError()

        cancelled_in_process = run_registry.request_cancel(run.id)
        if not cancelled_in_process:
            # Nothing in this worker is streaming the run (different
            # worker, or it already finished) — best-effort direct mark.
            self._runs.mark_cancelled(run, completed_at=datetime.now(UTC))
            await self._runs.flush()
            await self._session.commit()
        logger.info(
            "ai.chat.run_cancel_requested",
            run_id=str(run.id),
            in_process=cancelled_in_process,
        )


def _spawn_title_generation(chat_id: uuid.UUID) -> None:
    task = asyncio.create_task(_generate_title(chat_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _generate_title(chat_id: uuid.UUID) -> None:
    try:
        async with AsyncSessionLocal() as session:
            messages = ChatMessageRepository(session)

            chat = await session.get(Chat, chat_id)
            if chat is None or chat.title != DEFAULT_CHAT_TITLE:
                return

            first_message = await messages.get_first_user_message(chat_id)
            if first_message is None:
                return

            model, _capabilities = LLMFactory.create(chat.provider, chat.model, tools=[])
            response = await model.ainvoke(
                [build_title_system_message(), HumanMessage(content=first_message.content)]
            )
            title = _clean_title(response.content if isinstance(response.content, str) else "")
            if title:
                chat.title = title
                await session.commit()
    except Exception:
        logger.exception("ai.chat.title_generation_failed", chat_id=str(chat_id))


def _clean_title(raw: str) -> str:
    return raw.strip().strip('"').strip("'").strip()[:MAX_TITLE_LENGTH]
