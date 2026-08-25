"""Central tool registry: aggregates every domain's tools for one run,
bound to that run's trusted `ToolContext`.

`build_tool_registry(ctx)` is the only function `agent.graph` calls — it
never imports a domain tool module directly, so adding a new tool category
never touches the graph.
"""

from langchain_core.tools import BaseTool

from src.modules.ai_assistant.tools import analytics, categories, expenses, recurring, reports
from src.modules.ai_assistant.tools.context import ToolContext


def build_tool_registry(ctx: ToolContext) -> list[BaseTool]:
    return [
        *expenses.build_tools(ctx),
        *analytics.build_tools(ctx),
        *categories.build_tools(ctx),
        *recurring.build_tools(ctx),
        *reports.build_tools(ctx),
    ]
