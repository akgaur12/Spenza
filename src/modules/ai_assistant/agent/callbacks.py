"""Maps LangGraph's `astream_events` stream to `message_delta` SSE events
and accumulates per-run usage metadata.

Tool-level events (`tool_started`/`tool_result`) are emitted directly by
`agent.graph`'s `execute_tools` node instead — see that module's docstring
for why relying on `on_tool_start`/`on_tool_end`/`on_tool_error` tracing
events here would leave a cancelled/timed-out tool call's `tool_started`
without a matching result.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from src.modules.ai_assistant.agent.graph import EventSink
from src.modules.ai_assistant.streaming.events import message_delta


@dataclass
class RunMetadata:
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Incremented by `agent.runner` as `tool_started` events pass through
    # its consumer loop — this module never sees them directly (see the
    # module docstring), so it isn't tracked here.
    tool_calls: int = 0


def _extract_text(content: Any) -> str:
    """`AIMessageChunk.content` is usually a plain string, but some
    providers emit a list of content blocks (e.g. multimodal responses) —
    only the text blocks are relevant to this assistant's answers.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block.get("text", "") for block in content if isinstance(block, dict)]
        return "".join(parts)
    return ""


async def consume(
    astream_events: AsyncIterator[Any], on_event: EventSink, metadata: RunMetadata
) -> None:
    async for event in astream_events:
        kind = event.get("event")
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            text = _extract_text(chunk.content)
            if text:
                await on_event(message_delta(text))
        elif kind == "on_chat_model_end":
            usage = getattr(event["data"].get("output"), "usage_metadata", None)
            if usage:
                metadata.input_tokens = (metadata.input_tokens or 0) + usage.get("input_tokens", 0)
                metadata.output_tokens = (metadata.output_tokens or 0) + usage.get(
                    "output_tokens", 0
                )
