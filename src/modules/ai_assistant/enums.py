"""Enums for the `ai_assistant` module.

Mirrors the existing `Enum(PyEnum, native_enum=False, length=N)` convention
used by `users.models.UserRole`/`recurring_expenses.enums.Frequency` — a
portable, string-backed column so the same model works against both
Postgres (production) and SQLite (the test suite).

`LLMProvider` is deliberately reused as the type of
`Settings.AI_DEFAULT_PROVIDER` (see `src.core.app_config`) as well as the
`chats.provider`/`chat_runs.provider` columns — one enum, not a duplicate
settings-level `Literal`, since drift between the two would be a bug.
"""

from enum import StrEnum


class LLMProvider(StrEnum):
    """A supported LLM backend. See `ai_assistant.providers` for the adapter
    behind each value — the agent/graph never imports these directly.
    """

    OLLAMA = "ollama"
    AWS_BEDROCK = "aws_bedrock"
    GROQ = "groq"
    NVIDIA = "nvidia"
    OPENAI = "openai"
    HUGGINGFACE = "huggingface"
    OPEN_ROUTER = "open_router"


class ChatMessageRole(StrEnum):
    """Who authored a `ChatMessage`."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ChatRunStatus(StrEnum):
    """Lifecycle state of one agent execution (`ChatRun`).

    QUEUED     -> persisted, not yet streaming.
    RUNNING    -> the agent is actively working; cancellable.
    COMPLETED  -> finished normally; terminal.
    FAILED     -> the agent or a tool raised unrecoverably; terminal.
    CANCELLED  -> the user cancelled it; terminal.
    """

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
