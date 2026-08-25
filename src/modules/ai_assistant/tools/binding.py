"""Binds a tool-handler coroutine and its `args_schema` to one run's
`ToolContext`, producing a LangChain `BaseTool` the model can call.

Every domain module in `tools/` uses this so it only has to write the
handler logic (a plain `async def handler(ctx, args) -> str`) — never the
LangChain tool-construction boilerplate, and never a `user`/`session`
parameter the model could fill in itself.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from src.modules.ai_assistant.tools.context import ToolContext


def bind_tool(
    *,
    name: str,
    description: str,
    args_schema: type[BaseModel],
    handler: Callable[[ToolContext, Any], Awaitable[str]],
    ctx: ToolContext,
) -> BaseTool:
    async def _run(**kwargs: Any) -> str:
        return await handler(ctx, args_schema(**kwargs))

    return StructuredTool.from_function(
        name=name,
        description=description,
        args_schema=args_schema,
        coroutine=_run,
    )
