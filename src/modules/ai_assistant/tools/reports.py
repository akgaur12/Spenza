"""Read-only report-summary tool.

Deliberately does **not** call `ReportService.generate`/`generate_with_data`
(`src.modules.reports.service`) — that renders a full PDF with SVG chart
geometry, the wrong shape and wasteful for a chat answer. Instead this
composes the same primitives `ReportService` itself uses:
`DashboardService.get_range_summary` (current period + its
`previous_period()`) and `AnalyticsService.get_category_breakdown`.
"""

from decimal import ROUND_HALF_UP, Decimal

from langchain_core.tools import BaseTool

from src.modules.ai_assistant.tools.binding import bind_tool
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.period_utils import (
    percentage_change,
    previous,
    resolve_range,
    to_utc_bounds,
)
from src.modules.ai_assistant.tools.schemas import GetReportSummaryArgs
from src.modules.ai_assistant.tools.serialization import to_tool_result
from src.modules.analytics.service import AnalyticsService
from src.modules.dashboard.service import DashboardService

_CENTS = Decimal("0.01")


async def get_report_summary(ctx: ToolContext, args: GetReportSummaryArgs) -> str:
    current_range = resolve_range(args.start_date, args.end_date)
    previous_range = previous(current_range)

    dashboard = DashboardService(ctx.session)
    current_start, current_end, current_days = to_utc_bounds(current_range)
    previous_start, previous_end, previous_days = to_utc_bounds(previous_range)
    current_summary = await dashboard.get_range_summary(
        ctx.user, current_start, current_end, current_days
    )
    previous_summary = await dashboard.get_range_summary(
        ctx.user, previous_start, previous_end, previous_days
    )

    breakdown = await AnalyticsService(ctx.session).get_category_breakdown(
        ctx.user, current_range.start_date, current_range.end_date
    )
    top_categories = sorted(breakdown.categories, key=lambda item: item.total, reverse=True)[:5]

    difference = (current_summary.total - previous_summary.total).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )
    payload = {
        "period": {"start_date": current_range.start_date, "end_date": current_range.end_date},
        "total_spending": current_summary.total,
        "expense_count": current_summary.expense_count,
        "daily_average": current_summary.daily_average,
        "average_expense": current_summary.average_expense,
        "top_category": (
            current_summary.top_category.name if current_summary.top_category else None
        ),
        "largest_expense_description": (
            current_summary.largest_expense.description if current_summary.largest_expense else None
        ),
        "top_categories": [
            {"name": item.name, "total": item.total, "percentage": item.percentage}
            for item in top_categories
        ],
        "previous_period": {
            "start_date": previous_range.start_date,
            "end_date": previous_range.end_date,
            "total_spending": previous_summary.total,
        },
        "difference_vs_previous_period": difference,
        "percentage_change_vs_previous_period": percentage_change(
            current_summary.total, previous_summary.total
        ),
    }
    return to_tool_result(payload)


def build_tools(ctx: ToolContext) -> list[BaseTool]:
    return [
        bind_tool(
            name="get_report_summary",
            description=(
                "Get a summary report of the user's spending for a period: total, "
                "top categories, largest expense, and comparison with the previous "
                "equal-length period."
            ),
            args_schema=GetReportSummaryArgs,
            handler=get_report_summary,
            ctx=ctx,
        ),
    ]
