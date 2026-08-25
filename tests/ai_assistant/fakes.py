"""A scriptable, network-free LangChain chat model used everywhere a test
needs deterministic agent behavior — tool calls, multi-turn tool loops,
plain text answers, streamed chunks, usage metadata, and induced failures.

`FakeChatModel` is a genuine `BaseChatModel` (not a bare stub), so it goes
through the real LangGraph `astream_events` machinery exactly like a real
provider's chat model would — `on_chat_model_stream`/`on_chat_model_end`
fire for real, which is what `agent.callbacks` and `agent.runner` consume.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from pydantic import Field


@dataclass
class FakeTurn:
    """One scripted response to a single `.ainvoke()`/`.astream()` call."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    text_chunks: list[str] = field(default_factory=list)
    usage: dict[str, int] | None = None
    error: Exception | None = None
    # Simulates a slow/streaming provider — sleeps this long before each
    # yielded chunk, giving a test a window to e.g. cancel mid-stream.
    delay_seconds: float = 0.0


class FakeChatModel(BaseChatModel):
    """Consumes one `FakeTurn` from `turns` per call, in order. Raises an
    `AssertionError` if the graph calls it more times than the test
    scripted — a stuck tool-calling loop should fail loudly, not hang.
    """

    turns: list[FakeTurn] = Field(default_factory=list)
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise NotImplementedError("FakeChatModel only supports async streaming")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        index = self.calls
        self.calls += 1
        if index >= len(self.turns):
            raise AssertionError(
                f"FakeChatModel received call #{index + 1} but only {len(self.turns)} "
                "turn(s) were scripted."
            )
        turn = self.turns[index]
        if turn.error is not None:
            raise turn.error

        if turn.tool_calls:
            if turn.delay_seconds:
                await asyncio.sleep(turn.delay_seconds)
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=turn.tool_calls)
            )
            return

        for text in turn.text_chunks or [""]:
            if turn.delay_seconds:
                await asyncio.sleep(turn.delay_seconds)
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
        if turn.usage:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", usage_metadata=turn.usage))
