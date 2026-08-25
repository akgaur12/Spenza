"""Drives one agent run end to end: builds the graph, streams SSE events,
accumulates the final answer text, enforces `AI_AGENT_TIMEOUT_SECONDS`, and
supports cooperative cancellation via `run_registry`.

`AgentRunner` itself is stateless/reusable — the outcome of one call to
`stream()` is written into the `result_box` list the caller passes in
(appended once, after the terminal SSE event), rather than stored on
`self`, so one runner instance is safe to share across concurrent runs.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.core.logger import get_logger
from src.modules.ai_assistant.agent import graph as graph_module
from src.modules.ai_assistant.agent.callbacks import RunMetadata, consume
from src.modules.ai_assistant.agent.state import AgentState
from src.modules.ai_assistant.streaming.events import (
    SSEEvent,
    SSEEventType,
    message_completed,
    message_started,
    run_cancelled,
    run_completed,
    run_failed,
    run_started,
)

logger = get_logger(__name__)

_DONE = object()


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    content: str
    metadata: RunMetadata
    status: Literal["completed", "failed", "cancelled"]
    error: str | None = None


class RunRegistry:
    """In-memory `run_id -> cancel Event` map. Cancellation is scoped to
    this worker process — there's no cross-worker pub/sub broker in this
    codebase, so a run cancelled while being streamed by a *different*
    worker falls back to the DB-flag path in `ChatService.cancel_run`.
    """

    def __init__(self) -> None:
        self._events: dict[uuid.UUID, asyncio.Event] = {}

    def register(self, run_id: uuid.UUID) -> asyncio.Event:
        event = asyncio.Event()
        self._events[run_id] = event
        return event

    def unregister(self, run_id: uuid.UUID) -> None:
        self._events.pop(run_id, None)

    def request_cancel(self, run_id: uuid.UUID) -> bool:
        event = self._events.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    def is_tracked(self, run_id: uuid.UUID) -> bool:
        return run_id in self._events


run_registry = RunRegistry()


class AgentRunner:
    def __init__(self, *, agent_timeout_seconds: float, tool_timeout_seconds: float) -> None:
        self._agent_timeout_seconds = agent_timeout_seconds
        self._tool_timeout_seconds = tool_timeout_seconds

    async def stream(
        self,
        *,
        run_id: uuid.UUID,
        chat_id: uuid.UUID,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        provider: str,
        model_name: str,
        model: Runnable[Any, AIMessage],
        tools: Sequence[BaseTool],
        messages: list[BaseMessage],
        result_box: list[AgentRunResult],
    ) -> AsyncIterator[SSEEvent]:
        cancel_event = run_registry.register(run_id)
        queue: asyncio.Queue[Any] = asyncio.Queue()
        run_metadata = RunMetadata()
        content_parts: list[str] = []

        async def emit(event: SSEEvent) -> None:
            await queue.put(event)

        graph = graph_module.build_graph(
            model, tools, tool_timeout_seconds=self._tool_timeout_seconds, on_event=emit
        )
        state: AgentState = {
            "messages": messages,
            "user_id": str(user_id),
            "chat_id": str(chat_id),
            "run_id": str(run_id),
            "provider": provider,
            "model": model_name,
            "tool_results": [],
            "metadata": {},
        }

        async def drive() -> None:
            try:
                await consume(graph.astream_events(state, version="v2"), emit, run_metadata)
            finally:
                await queue.put(_DONE)

        driver_task = asyncio.ensure_future(drive())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._agent_timeout_seconds

        def finish(
            status: Literal["completed", "failed", "cancelled"], error: str | None = None
        ) -> None:
            result_box.append(
                AgentRunResult(
                    content="".join(content_parts),
                    metadata=run_metadata,
                    status=status,
                    error=error,
                )
            )

        try:
            yield run_started(str(run_id), str(chat_id))
            yield message_started(str(message_id))

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    driver_task.cancel()
                    error = "The assistant took too long to respond."
                    finish("failed", error)
                    yield run_failed(str(run_id), error=error)
                    return

                get_task = asyncio.ensure_future(queue.get())
                cancel_task = asyncio.ensure_future(cancel_event.wait())
                done, pending = await asyncio.wait(
                    {get_task, cancel_task}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                )
                for pending_task in pending:
                    pending_task.cancel()

                if cancel_task in done:
                    driver_task.cancel()
                    finish("cancelled")
                    yield run_cancelled(str(run_id))
                    return

                if get_task not in done:
                    # `asyncio.wait`'s own timeout elapsed with nothing ready —
                    # loop back so the top-of-loop deadline check reports it.
                    continue

                event = get_task.result()
                if event is _DONE:
                    break
                if event.event is SSEEventType.MESSAGE_DELTA:
                    content_parts.append(event.data["content"])
                elif event.event is SSEEventType.TOOL_STARTED:
                    run_metadata.tool_calls += 1
                yield event

            if driver_task.done() and not driver_task.cancelled() and driver_task.exception():
                logger.exception(
                    "ai.agent.run_failed", run_id=str(run_id), exc_info=driver_task.exception()
                )
                error = "The assistant failed to respond. Please try again."
                finish("failed", error)
                yield run_failed(str(run_id), error=error)
                return

            final_content = "".join(content_parts)
            finish("completed")
            yield message_completed(str(message_id), final_content)
            yield run_completed(str(run_id))
        finally:
            run_registry.unregister(run_id)
