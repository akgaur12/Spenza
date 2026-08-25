"""Read-only spending-analytics tools.

`get_daily/weekly/monthly/yearly_spending` and `get_spending_trends` are all
the same underlying call — `AnalyticsService.get_trends(interval, ...)`
(`src.modules.analytics.service`) — with `interval` fixed per tool for the
first four. `get_category_spending`/`get_top_categories` both reuse
`AnalyticsService.get_category_breakdown`; "top N" is sorted/sliced in
Python since no dedicated ranked/limited method exists.

`get_largest_expenses` and `compare_periods` close gaps with pure
composition rather than new service/repository methods: the former sorts a
bounded `ExpenseService.list_for_user` page by amount, the latter calls
`DashboardService.get_range_summary` twice (the requested range, and its
`previous_period()`) and computes the delta itself.
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
from src.modules.ai_assistant.tools.schemas import (
    ComparePeriodsArgs,
    DateRangeArgs,
    GetCategorySpendingArgs,
    GetLargestExpensesArgs,
    GetSpendingTrendsArgs,
    GetTopCategoriesArgs,
)
from src.modules.ai_assistant.tools.serialization import to_tool_result
from src.modules.analytics.schemas import TrendInterval
from src.modules.analytics.service import AnalyticsService
from src.modules.dashboard.schemas import RangeSummary
from src.modules.dashboard.service import DashboardService
from src.modules.expenses.service import ExpenseService

_CENTS = Decimal("0.01")
# Bounds how many of the user's expenses `get_largest_expenses` scans in
# Python to rank by amount — generous enough for a single reporting period,
# far cheaper than loading every expense the user has ever recorded.
_LARGEST_EXPENSES_SCAN_LIMIT = 500


async def _trends(ctx: ToolContext, interval: TrendInterval, args: DateRangeArgs) -> str:
    trends = await AnalyticsService(ctx.session).get_trends(
        ctx.user, interval, args.start_date, args.end_date
    )
    payload = {
        "interval": trends.interval.value,
        "start_date": trends.start_date,
        "end_date": trends.end_date,
        "total_spending": trends.total_spending,
        "expense_count": trends.expense_count,
        "data": [
            {
                "period": point.period,
                "total": point.total,
                "expense_count": point.expense_count,
                "average_expense": point.average_expense,
            }
            for point in trends.data
        ],
    }
    return to_tool_result(payload)


async def get_daily_spending(ctx: ToolContext, args: DateRangeArgs) -> str:
    return await _trends(ctx, TrendInterval.DAILY, args)


async def get_weekly_spending(ctx: ToolContext, args: DateRangeArgs) -> str:
    return await _trends(ctx, TrendInterval.WEEKLY, args)


async def get_monthly_spending(ctx: ToolContext, args: DateRangeArgs) -> str:
    return await _trends(ctx, TrendInterval.MONTHLY, args)


async def get_yearly_spending(ctx: ToolContext, args: DateRangeArgs) -> str:
    return await _trends(ctx, TrendInterval.YEARLY, args)


async def get_spending_trends(ctx: ToolContext, args: GetSpendingTrendsArgs) -> str:
    return await _trends(ctx, args.interval, args)


async def get_category_spending(ctx: ToolContext, args: GetCategorySpendingArgs) -> str:
    breakdown = await AnalyticsService(ctx.session).get_category_breakdown(
        ctx.user, args.start_date, args.end_date
    )
    payload = {
        "start_date": breakdown.start_date,
        "end_date": breakdown.end_date,
        "total_spending": breakdown.total_spending,
        "categories": [
            {
                "name": item.name,
                "total": item.total,
                "expense_count": item.expense_count,
                "percentage": item.percentage,
                "average_expense": item.average_expense,
            }
            for item in breakdown.categories
        ],
    }
    return to_tool_result(payload)


async def get_top_categories(ctx: ToolContext, args: GetTopCategoriesArgs) -> str:
    breakdown = await AnalyticsService(ctx.session).get_category_breakdown(
        ctx.user, args.start_date, args.end_date
    )
    top = sorted(breakdown.categories, key=lambda item: item.total, reverse=True)[: args.limit]
    payload = {
        "start_date": breakdown.start_date,
        "end_date": breakdown.end_date,
        "top_categories": [
            {"name": item.name, "total": item.total, "percentage": item.percentage} for item in top
        ],
    }
    return to_tool_result(payload)


async def get_largest_expenses(ctx: ToolContext, args: GetLargestExpensesArgs) -> str:
    expenses, total_matching = await ExpenseService(ctx.session).list_for_user(
        ctx.user,
        category_ids=None,
        start_date=args.start_date,
        end_date=args.end_date,
        min_amount=None,
        max_amount=None,
        search=None,
        page=1,
        page_size=_LARGEST_EXPENSES_SCAN_LIMIT,
    )
    largest = sorted(expenses, key=lambda e: e.amount, reverse=True)[: args.limit]
    payload = {
        "scanned": len(expenses),
        "total_matching_range": total_matching,
        "largest_expenses": [
            {
                "id": str(e.id),
                "description": e.description,
                "amount": e.amount,
                "spent_at": e.spent_at,
                "category": e.category.name,
            }
            for e in largest
        ],
    }
    return to_tool_result(payload)


def _summary_payload(summary: RangeSummary) -> dict[str, object]:
    return {
        "total": summary.total,
        "expense_count": summary.expense_count,
        "top_category": summary.top_category.name if summary.top_category else None,
    }


async def compare_periods(ctx: ToolContext, args: ComparePeriodsArgs) -> str:
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

    difference = (current_summary.total - previous_summary.total).quantize(
        _CENTS, rounding=ROUND_HALF_UP
    )
    payload = {
        "current_period": {
            "start_date": current_range.start_date,
            "end_date": current_range.end_date,
            **_summary_payload(current_summary),
        },
        "previous_period": {
            "start_date": previous_range.start_date,
            "end_date": previous_range.end_date,
            **_summary_payload(previous_summary),
        },
        "difference": difference,
        "percentage_change": percentage_change(current_summary.total, previous_summary.total),
        "trend": "up" if difference > 0 else "down" if difference < 0 else "same",
    }
    return to_tool_result(payload)


def build_tools(ctx: ToolContext) -> list[BaseTool]:
    return [
        bind_tool(
            name="get_daily_spending",
            description="Get the user's spending broken down by day for a date range.",
            args_schema=DateRangeArgs,
            handler=get_daily_spending,
            ctx=ctx,
        ),
        bind_tool(
            name="get_weekly_spending",
            description="Get the user's spending broken down by week for a date range.",
            args_schema=DateRangeArgs,
            handler=get_weekly_spending,
            ctx=ctx,
        ),
        bind_tool(
            name="get_monthly_spending",
            description="Get the user's spending broken down by month for a date range.",
            args_schema=DateRangeArgs,
            handler=get_monthly_spending,
            ctx=ctx,
        ),
        bind_tool(
            name="get_yearly_spending",
            description="Get the user's spending broken down by year for a date range.",
            args_schema=DateRangeArgs,
            handler=get_yearly_spending,
            ctx=ctx,
        ),
        bind_tool(
            name="get_spending_trends",
            description="Get the user's spending trend over time at a chosen interval.",
            args_schema=GetSpendingTrendsArgs,
            handler=get_spending_trends,
            ctx=ctx,
        ),
        bind_tool(
            name="get_category_spending",
            description="Get the user's spending broken down by category for a date range.",
            args_schema=GetCategorySpendingArgs,
            handler=get_category_spending,
            ctx=ctx,
        ),
        bind_tool(
            name="get_top_categories",
            description="Get the user's highest-spending categories for a date range.",
            args_schema=GetTopCategoriesArgs,
            handler=get_top_categories,
            ctx=ctx,
        ),
        bind_tool(
            name="get_largest_expenses",
            description="Get the user's largest individual expenses for a date range.",
            args_schema=GetLargestExpensesArgs,
            handler=get_largest_expenses,
            ctx=ctx,
        ),
        bind_tool(
            name="compare_periods",
            description=(
                "Compare the user's total spending in a given period against the "
                "equal-length period immediately before it (e.g. this month vs last "
                "month)."
            ),
            args_schema=ComparePeriodsArgs,
            handler=compare_periods,
            ctx=ctx,
        ),
    ]
