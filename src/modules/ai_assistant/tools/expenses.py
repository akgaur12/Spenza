"""Read-only expense tools.

Reuses `ExpenseService.list_for_user`/`get_for_user`
(`src.modules.expenses.service`) and `CategoryService.list_for_user`
(to resolve an LLM-supplied category *name* into a `category_id`, since the
model has no way to know a category's UUID). `get_total_spending` composes
`DashboardService.get_range_summary` rather than re-summing expenses
itself, matching what the dashboard/reports modules already do for "total
spend in a period".
"""

import uuid
from decimal import Decimal
from typing import Any

from langchain_core.tools import BaseTool

from src.modules.ai_assistant.tools.binding import bind_tool
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.period_utils import resolve_range, to_utc_bounds
from src.modules.ai_assistant.tools.schemas import (
    GetExpenseArgs,
    GetExpensesArgs,
    GetTotalSpendingArgs,
    SearchExpensesArgs,
)
from src.modules.ai_assistant.tools.serialization import to_tool_result
from src.modules.categories.models import Category
from src.modules.categories.service import CategoryService
from src.modules.dashboard.service import DashboardService
from src.modules.expenses.exceptions import ExpenseNotFoundError
from src.modules.expenses.models import Expense
from src.modules.expenses.service import ExpenseService


async def _resolve_category_id(
    ctx: ToolContext, category: str | None
) -> tuple[uuid.UUID | None, str | None]:
    """An exact case-insensitive name match wins; otherwise the first
    search hit. `(None, None)` if `category` matches nothing the user has
    — callers surface that as a note rather than silently dropping the
    filter or guessing a category.
    """
    if not category:
        return None, None
    categories = await CategoryService(ctx.session).list_for_user(ctx.user, search=category)
    if not categories:
        return None, None
    exact = next((c for c in categories if c.name.lower() == category.lower()), None)
    match = exact or categories[0]
    return match.id, match.name


def _expense_payload(expense: Expense, category: Category) -> dict[str, Any]:
    return {
        "id": str(expense.id),
        "description": expense.description,
        "amount": expense.amount,
        "spent_at": expense.spent_at,
        "category": category.name,
    }


async def get_expenses(ctx: ToolContext, args: GetExpensesArgs) -> str:
    category_id, matched_name = await _resolve_category_id(ctx, args.category)
    expenses, total = await ExpenseService(ctx.session).list_for_user(
        ctx.user,
        category_ids=[category_id] if category_id else None,
        start_date=args.start_date,
        end_date=args.end_date,
        min_amount=Decimal(str(args.min_amount)) if args.min_amount is not None else None,
        max_amount=Decimal(str(args.max_amount)) if args.max_amount is not None else None,
        search=None,
        page=args.page,
        page_size=args.page_size,
    )
    payload = {
        "total_matching": total,
        "page": args.page,
        "page_size": args.page_size,
        "category_filter_matched": matched_name,
        "category_filter_unmatched": (
            args.category if args.category and category_id is None else None
        ),
        "expenses": [_expense_payload(e, e.category) for e in expenses],
    }
    return to_tool_result(payload)


async def search_expenses(ctx: ToolContext, args: SearchExpensesArgs) -> str:
    expenses, total = await ExpenseService(ctx.session).list_for_user(
        ctx.user,
        category_ids=None,
        start_date=args.start_date,
        end_date=args.end_date,
        min_amount=None,
        max_amount=None,
        search=args.search_term,
        page=args.page,
        page_size=args.page_size,
    )
    payload = {
        "total_matching": total,
        "page": args.page,
        "page_size": args.page_size,
        "expenses": [_expense_payload(e, e.category) for e in expenses],
    }
    return to_tool_result(payload)


async def get_expense(ctx: ToolContext, args: GetExpenseArgs) -> str:
    try:
        expense_id = uuid.UUID(args.expense_id)
    except ValueError:
        return to_tool_result({"found": False, "reason": "not a valid expense id"})

    try:
        expense = await ExpenseService(ctx.session).get_for_user(expense_id, ctx.user)
    except ExpenseNotFoundError:
        return to_tool_result({"found": False})
    return to_tool_result({"found": True, "expense": _expense_payload(expense, expense.category)})


async def get_total_spending(ctx: ToolContext, args: GetTotalSpendingArgs) -> str:
    resolved = resolve_range(args.start_date, args.end_date)
    start_utc, end_utc, span_days = to_utc_bounds(resolved)
    summary = await DashboardService(ctx.session).get_range_summary(
        ctx.user, start_utc, end_utc, span_days
    )
    payload = {
        "start_date": resolved.start_date,
        "end_date": resolved.end_date,
        "total": summary.total,
        "expense_count": summary.expense_count,
        "daily_average": summary.daily_average,
        "average_expense": summary.average_expense,
        "top_category": summary.top_category.name if summary.top_category else None,
        "largest_expense_description": (
            summary.largest_expense.description if summary.largest_expense else None
        ),
    }
    return to_tool_result(payload)


def build_tools(ctx: ToolContext) -> list[BaseTool]:
    return [
        bind_tool(
            name="get_expenses",
            description=(
                "List the user's expenses, optionally filtered by category name, date "
                "range, or amount range. Returns matching expenses (paginated)."
            ),
            args_schema=GetExpensesArgs,
            handler=get_expenses,
            ctx=ctx,
        ),
        bind_tool(
            name="search_expenses",
            description="Search the user's expenses by text in their description.",
            args_schema=SearchExpensesArgs,
            handler=search_expenses,
            ctx=ctx,
        ),
        bind_tool(
            name="get_expense",
            description="Get full details of one specific expense by its exact id.",
            args_schema=GetExpenseArgs,
            handler=get_expense,
            ctx=ctx,
        ),
        bind_tool(
            name="get_total_spending",
            description=(
                "Get the user's total spending for a date range (defaults to the "
                "current calendar month if no range is given)."
            ),
            args_schema=GetTotalSpendingArgs,
            handler=get_total_spending,
            ctx=ctx,
        ),
    ]
