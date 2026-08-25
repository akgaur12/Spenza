"""Read-only recurring-expense tools.

All three reuse `RecurringExpenseService.list_for_user`
(`src.modules.recurring_expenses.service`) — there's no dedicated "upcoming
occurrences" or "summary" method, so `get_upcoming_recurring_expenses` and
`get_recurring_expense_summary` both filter/aggregate the same list in
Python rather than adding a new service/repository method.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from langchain_core.tools import BaseTool

from src.core.timezone import APP_TIMEZONE
from src.modules.ai_assistant.tools.binding import bind_tool
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.schemas import (
    GetRecurringExpensesArgs,
    GetUpcomingRecurringExpensesArgs,
    NoArgs,
)
from src.modules.ai_assistant.tools.serialization import to_tool_result
from src.modules.recurring_expenses.enums import (
    RecurringExpenseSortField,
    RecurringExpenseStatus,
    SortOrder,
)
from src.modules.recurring_expenses.models import RecurringExpense
from src.modules.recurring_expenses.service import RecurringExpenseService

# Wide enough to cover any one user's recurring expenses in a single scan
# for the upcoming/summary tools, which aggregate in Python rather than SQL.
_SCAN_LIMIT = 500

# Approximate months-per-year normalization factor for each frequency, used
# only to express "total monthly commitment" in `get_recurring_expense_summary`.
_OCCURRENCES_PER_MONTH: dict[str, Decimal] = {
    "daily": Decimal("30.44"),
    "weekly": Decimal("4.345"),
    "monthly": Decimal("1"),
    "quarterly": Decimal("0.333"),
    "yearly": Decimal("0.0833"),
}


def _recurring_payload(recurring: RecurringExpense) -> dict[str, object]:
    return {
        "id": str(recurring.id),
        "description": recurring.description,
        "amount": recurring.amount,
        "category": recurring.category.name,
        "frequency": recurring.frequency.value,
        "status": recurring.status.value,
        "next_run_date": recurring.next_run_date,
        "last_run_date": recurring.last_run_date,
    }


async def get_recurring_expenses(ctx: ToolContext, args: GetRecurringExpensesArgs) -> str:
    items, total = await RecurringExpenseService(ctx.session).list_for_user(
        ctx.user,
        status=args.status,
        frequency=args.frequency,
        generation_mode=None,
        search=args.search,
        sort_by=RecurringExpenseSortField.NEXT_RUN_DATE,
        sort_order=SortOrder.ASC,
        page=args.page,
        page_size=args.page_size,
    )
    payload = {
        "total_matching": total,
        "page": args.page,
        "page_size": args.page_size,
        "recurring_expenses": [_recurring_payload(r) for r in items],
    }
    return to_tool_result(payload)


async def get_upcoming_recurring_expenses(
    ctx: ToolContext, args: GetUpcomingRecurringExpensesArgs
) -> str:
    items, _ = await RecurringExpenseService(ctx.session).list_for_user(
        ctx.user,
        status=RecurringExpenseStatus.ACTIVE,
        frequency=None,
        generation_mode=None,
        search=None,
        sort_by=RecurringExpenseSortField.NEXT_RUN_DATE,
        sort_order=SortOrder.ASC,
        page=1,
        page_size=_SCAN_LIMIT,
    )
    today = datetime.now(APP_TIMEZONE).date()
    cutoff = today + timedelta(days=args.days_ahead)
    upcoming = [r for r in items if today <= r.next_run_date <= cutoff]
    payload = {
        "days_ahead": args.days_ahead,
        "upcoming": [_recurring_payload(r) for r in upcoming],
    }
    return to_tool_result(payload)


async def get_recurring_expense_summary(ctx: ToolContext, _args: NoArgs) -> str:
    items, _ = await RecurringExpenseService(ctx.session).list_for_user(
        ctx.user,
        status=RecurringExpenseStatus.ACTIVE,
        frequency=None,
        generation_mode=None,
        search=None,
        sort_by=RecurringExpenseSortField.NEXT_RUN_DATE,
        sort_order=SortOrder.ASC,
        page=1,
        page_size=_SCAN_LIMIT,
    )

    count_by_frequency: dict[str, int] = {}
    monthly_commitment = Decimal("0.00")
    for recurring in items:
        frequency = recurring.frequency.value
        count_by_frequency[frequency] = count_by_frequency.get(frequency, 0) + 1
        factor = _OCCURRENCES_PER_MONTH.get(frequency, Decimal("0"))
        monthly_commitment += recurring.amount * factor

    payload = {
        "active_count": len(items),
        "count_by_frequency": count_by_frequency,
        "estimated_monthly_commitment": monthly_commitment.quantize(Decimal("0.01")),
    }
    return to_tool_result(payload)


def build_tools(ctx: ToolContext) -> list[BaseTool]:
    return [
        bind_tool(
            name="get_recurring_expenses",
            description="List the user's recurring expenses (subscriptions, bills, ...).",
            args_schema=GetRecurringExpensesArgs,
            handler=get_recurring_expenses,
            ctx=ctx,
        ),
        bind_tool(
            name="get_upcoming_recurring_expenses",
            description="List the user's recurring expenses due within the next N days.",
            args_schema=GetUpcomingRecurringExpensesArgs,
            handler=get_upcoming_recurring_expenses,
            ctx=ctx,
        ),
        bind_tool(
            name="get_recurring_expense_summary",
            description=(
                "Get a summary of the user's active recurring expenses: how many, by "
                "frequency, and the estimated total monthly commitment."
            ),
            args_schema=NoArgs,
            handler=get_recurring_expense_summary,
            ctx=ctx,
        ),
    ]
