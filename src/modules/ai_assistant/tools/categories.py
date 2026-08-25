"""Read-only category tools.

`get_categories` reuses `CategoryService.list_for_user`
(`src.modules.categories.service`). `compare_categories` composes
`AnalyticsService.get_category_breakdown` for the requested period and its
`previous_period()`, computing the per-category delta itself — the same
gap-closing pattern as `analytics.compare_periods`.
"""

from decimal import ROUND_HALF_UP, Decimal

from langchain_core.tools import BaseTool

from src.modules.ai_assistant.tools.binding import bind_tool
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.period_utils import previous, resolve_range
from src.modules.ai_assistant.tools.schemas import CompareCategoriesArgs, GetCategoriesArgs
from src.modules.ai_assistant.tools.serialization import to_tool_result
from src.modules.analytics.schemas import CategoryAnalyticsItem
from src.modules.analytics.service import AnalyticsService
from src.modules.categories.service import CategoryService

_CENTS = Decimal("0.01")


async def get_categories(ctx: ToolContext, args: GetCategoriesArgs) -> str:
    categories = await CategoryService(ctx.session).list_for_user(ctx.user, search=args.search)
    payload = {"categories": [{"name": c.name, "is_system": c.user_id is None} for c in categories]}
    return to_tool_result(payload)


def _by_name(items: list[CategoryAnalyticsItem]) -> dict[str, CategoryAnalyticsItem]:
    return {item.name: item for item in items}


async def compare_categories(ctx: ToolContext, args: CompareCategoriesArgs) -> str:
    current_range = resolve_range(args.start_date, args.end_date)
    previous_range = previous(current_range)

    analytics = AnalyticsService(ctx.session)
    current = await analytics.get_category_breakdown(
        ctx.user, current_range.start_date, current_range.end_date
    )
    previous_breakdown = await analytics.get_category_breakdown(
        ctx.user, previous_range.start_date, previous_range.end_date
    )

    current_by_name = _by_name(current.categories)
    previous_by_name = _by_name(previous_breakdown.categories)
    names = current_by_name.keys() | previous_by_name.keys()

    deltas: list[tuple[str, Decimal, Decimal, Decimal]] = []
    for name in names:
        current_total = current_by_name[name].total if name in current_by_name else Decimal("0.00")
        previous_total = (
            previous_by_name[name].total if name in previous_by_name else Decimal("0.00")
        )
        difference = (current_total - previous_total).quantize(_CENTS, rounding=ROUND_HALF_UP)
        deltas.append((name, current_total, previous_total, difference))
    deltas.sort(key=lambda row: row[3], reverse=True)

    comparisons = [
        {
            "name": name,
            "current_total": current_total,
            "previous_total": previous_total,
            "difference": difference,
        }
        for name, current_total, previous_total, difference in deltas
    ]

    payload = {
        "current_period": {
            "start_date": current_range.start_date,
            "end_date": current_range.end_date,
        },
        "previous_period": {
            "start_date": previous_range.start_date,
            "end_date": previous_range.end_date,
        },
        "categories": comparisons,
    }
    return to_tool_result(payload)


def build_tools(ctx: ToolContext) -> list[BaseTool]:
    return [
        bind_tool(
            name="get_categories",
            description="List the user's available expense categories.",
            args_schema=GetCategoriesArgs,
            handler=get_categories,
            ctx=ctx,
        ),
        bind_tool(
            name="compare_categories",
            description=(
                "Compare the user's per-category spending in a given period against "
                "the equal-length period immediately before it."
            ),
            args_schema=CompareCategoriesArgs,
            handler=compare_categories,
            ctx=ctx,
        ),
    ]
