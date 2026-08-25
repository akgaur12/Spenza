"""The 9 SSE event types the assistant streams to the client, and the
dataclass used to carry them from `agent.callbacks`/`agent.runner` through
`ai_assistant.service` to `streaming.sse`.

Payloads never include provider credentials, the system prompt, or raw
tool-call arguments — a `tool_started`/`tool_result` event names the tool
(mirroring the spec's own example), which is a UI affordance distinct from
the assistant's actual reply text, which must never name a tool itself
(see `agent.prompts`).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SSEEventType(StrEnum):
    RUN_STARTED = "run_started"
    MESSAGE_STARTED = "message_started"
    TOOL_STARTED = "tool_started"
    TOOL_RESULT = "tool_result"
    MESSAGE_DELTA = "message_delta"
    MESSAGE_COMPLETED = "message_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


@dataclass(frozen=True, slots=True)
class SSEEvent:
    event: SSEEventType
    data: dict[str, Any] = field(default_factory=dict)


def run_started(run_id: str, chat_id: str) -> SSEEvent:
    return SSEEvent(SSEEventType.RUN_STARTED, {"run_id": run_id, "chat_id": chat_id})


def message_started(message_id: str) -> SSEEvent:
    return SSEEvent(SSEEventType.MESSAGE_STARTED, {"message_id": message_id})


def tool_started(tool: str) -> SSEEvent:
    return SSEEvent(SSEEventType.TOOL_STARTED, {"tool": tool})


def tool_result(tool: str, *, status: str) -> SSEEvent:
    return SSEEvent(SSEEventType.TOOL_RESULT, {"tool": tool, "status": status})


def message_delta(content: str) -> SSEEvent:
    return SSEEvent(SSEEventType.MESSAGE_DELTA, {"content": content})


def message_completed(message_id: str, content: str) -> SSEEvent:
    return SSEEvent(SSEEventType.MESSAGE_COMPLETED, {"message_id": message_id, "content": content})


def run_completed(run_id: str) -> SSEEvent:
    return SSEEvent(SSEEventType.RUN_COMPLETED, {"run_id": run_id, "status": "completed"})


def run_failed(run_id: str, *, error: str) -> SSEEvent:
    return SSEEvent(SSEEventType.RUN_FAILED, {"run_id": run_id, "status": "failed", "error": error})


def run_cancelled(run_id: str) -> SSEEvent:
    return SSEEvent(SSEEventType.RUN_CANCELLED, {"run_id": run_id, "status": "cancelled"})
