"""Typed LangGraph state for one agent run.

Deliberately holds only IDs, strings, and message history — never a raw
`AsyncSession` or `User` object (see spec rule: the agent must never touch
the database directly; tool execution gets its trusted `ToolContext` from
`agent.runner`/`tools.registry`, not from this state).
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    chat_id: str
    run_id: str
    provider: str
    model: str
    tool_results: list[dict[str, object]]
    metadata: dict[str, object]
