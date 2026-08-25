"""The trusted context every tool closes over.

`ToolContext` is constructed once per run by `ai_assistant.service`/
`agent.runner` from the *authenticated request's* `CurrentUser` and
`AsyncSession` — never from anything LLM-supplied. Tool functions receive
it via closure (see `registry.build_tool_registry`), so `user`/`session`
can never appear in a tool's `args_schema` and are never fillable by the
model.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.users.models import User


@dataclass(frozen=True, slots=True)
class ToolContext:
    user: User
    session: AsyncSession
