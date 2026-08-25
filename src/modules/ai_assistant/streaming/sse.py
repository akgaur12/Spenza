"""Encodes `SSEEvent`s as `text/event-stream` bytes and wraps an async
generator of them in a `StreamingResponse`.
"""

import json
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from src.modules.ai_assistant.streaming.events import SSEEvent


def sse_encode(event: SSEEvent) -> str:
    return f"event: {event.event.value}\ndata: {json.dumps(event.data, default=str)}\n\n"


def sse_response(events: AsyncIterator[SSEEvent]) -> StreamingResponse:
    async def encoded() -> AsyncIterator[str]:
        async for event in events:
            yield sse_encode(event)

    return StreamingResponse(
        encoded(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
