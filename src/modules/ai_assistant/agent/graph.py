"""The agent graph: `call_model -> tool call? -> execute_tools -> back to
call_model -> ... -> END`, supporting multiple sequential tool calls.

`model` is a provider-agnostic LangChain `Runnable` (already bound with
`tools`), built one layer up by `providers.factory.LLMFactory` — this
module never imports a concrete provider or LangChain chat-model class,
only `Runnable`/`BaseTool`/message types.

This is the one place that enforces `AI_TOOL_TIMEOUT_SECONDS` per tool
call; a tool that raises or times out becomes an error `ToolMessage` fed
back to the model rather than aborting the run — the model decides how to
explain that to the user. `execute_tools` also emits `tool_started`/
`tool_result` SSE events directly (via `on_event`) rather than relying on
LangChain's tracing events for this: a cancelled/timed-out tool call's
traced span never reliably closes with a matching `on_tool_end`/
`on_tool_error`, which would leave a `tool_started` with no matching
result in the stream.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.core.logger import get_logger
from src.modules.ai_assistant.agent.state import AgentState
from src.modules.ai_assistant.streaming.events import SSEEvent, tool_result, tool_started

logger = get_logger(__name__)

CALL_MODEL = "call_model"
EXECUTE_TOOLS = "execute_tools"

EventSink = Callable[[SSEEvent], Awaitable[None]]


def _build_call_model(model: Runnable[Any, AIMessage]) -> Any:
    async def call_model(state: AgentState) -> dict[str, Any]:
        response = await model.ainvoke(state["messages"])
        return {"messages": [response]}

    return call_model


def _build_execute_tools(
    tools: Sequence[BaseTool], *, tool_timeout_seconds: float, on_event: EventSink
) -> Any:
    tools_by_name = {t.name: t for t in tools}

    async def execute_tools(state: AgentState) -> dict[str, Any]:
        last_message = state["messages"][-1]
        tool_calls = last_message.tool_calls if isinstance(last_message, AIMessage) else []

        tool_messages: list[ToolMessage] = []
        for call in tool_calls:
            await on_event(tool_started(call["name"]))
            tool_messages.append(
                await _invoke_one(tools_by_name, call, tool_timeout_seconds, on_event)
            )
        return {"messages": tool_messages}

    return execute_tools


async def _invoke_one(
    tools_by_name: dict[str, BaseTool],
    call: ToolCall,
    tool_timeout_seconds: float,
    on_event: EventSink,
) -> ToolMessage:
    tool = tools_by_name.get(call["name"])
    if tool is None:
        await on_event(tool_result(call["name"], status="error"))
        content = json.dumps({"error": f"Unknown tool: {call['name']}"})
        return ToolMessage(content=content, tool_call_id=call["id"], name=call["name"])

    try:
        result = await asyncio.wait_for(tool.ainvoke(call["args"]), timeout=tool_timeout_seconds)
        content = result if isinstance(result, str) else json.dumps(result, default=str)
        await on_event(tool_result(call["name"], status="ok"))
    except TimeoutError:
        logger.warning("ai.tool.timeout", tool=call["name"])
        content = json.dumps({"error": "This tool took too long to respond."})
        await on_event(tool_result(call["name"], status="error"))
    except Exception:
        logger.exception("ai.tool.failed", tool=call["name"])
        content = json.dumps({"error": "This tool failed to return a result."})
        await on_event(tool_result(call["name"], status="error"))
    return ToolMessage(content=content, tool_call_id=call["id"], name=call["name"])


def _should_continue(state: AgentState) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return EXECUTE_TOOLS
    return END


def build_graph(
    model: Runnable[Any, AIMessage],
    tools: Sequence[BaseTool],
    *,
    tool_timeout_seconds: float,
    on_event: EventSink,
) -> CompiledStateGraph[AgentState, Any, Any]:
    graph = StateGraph(AgentState)
    graph.add_node(CALL_MODEL, _build_call_model(model))
    graph.add_node(
        EXECUTE_TOOLS,
        _build_execute_tools(tools, tool_timeout_seconds=tool_timeout_seconds, on_event=on_event),
    )
    graph.set_entry_point(CALL_MODEL)
    graph.add_conditional_edges(
        CALL_MODEL, _should_continue, {EXECUTE_TOOLS: EXECUTE_TOOLS, END: END}
    )
    graph.add_edge(EXECUTE_TOOLS, CALL_MODEL)
    return graph.compile()
