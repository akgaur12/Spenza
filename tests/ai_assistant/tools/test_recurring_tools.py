"""Tests for the recurring-expense tools: correctness, user isolation, and
`args_schema` safety.
"""

import json

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.ai_assistant.tools import recurring as recurring_tools
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.schemas import (
    GetRecurringExpensesArgs,
    GetUpcomingRecurringExpensesArgs,
    NoArgs,
)
from tests.ai_assistant.helpers import (
    USER_A_SIGNUP,
    USER_B_SIGNUP,
    category_id_by_name,
    create_recurring_expense,
    get_user,
    login_user_a,
    login_user_b,
)
from tests.conftest import RecordingEmailBackend


def test_no_tool_args_schema_exposes_user() -> None:
    for schema in (GetRecurringExpensesArgs, GetUpcomingRecurringExpensesArgs, NoArgs):
        assert "user" not in schema.model_fields
        assert "user_id" not in schema.model_fields


async def test_get_recurring_expenses_isolated_between_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_recurring_expense(
        client,
        category_id=food_id,
        start_date="2026-01-01",
        frequency="monthly",
        description="Meal plan",
        amount="500.00",
    )

    await login_user_b(client, email_backend)
    b_food_id = await category_id_by_name(client, "Food")
    await create_recurring_expense(
        client,
        category_id=b_food_id,
        start_date="2026-01-01",
        frequency="weekly",
        description="Gym",
        amount="50.00",
    )

    async with db_session_factory() as session:
        user_a = await get_user(session, USER_A_SIGNUP["email"])
        ctx_a = ToolContext(user=user_a, session=session)
        result_a = json.loads(
            await recurring_tools.get_recurring_expenses(
                ctx_a,
                GetRecurringExpensesArgs(
                    status=None, frequency=None, search=None, page=1, page_size=20
                ),
            )
        )
        assert result_a["total_matching"] == 1
        assert result_a["recurring_expenses"][0]["description"] == "Meal plan"

        user_b = await get_user(session, USER_B_SIGNUP["email"])
        ctx_b = ToolContext(user=user_b, session=session)
        result_b = json.loads(
            await recurring_tools.get_recurring_expenses(
                ctx_b,
                GetRecurringExpensesArgs(
                    status=None, frequency=None, search=None, page=1, page_size=20
                ),
            )
        )
        assert result_b["total_matching"] == 1
        assert result_b["recurring_expenses"][0]["description"] == "Gym"


async def test_recurring_expense_summary_aggregates_by_frequency(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_recurring_expense(
        client,
        category_id=food_id,
        start_date="2026-01-01",
        frequency="monthly",
        description="Meal plan",
        amount="500.00",
    )
    await create_recurring_expense(
        client,
        category_id=food_id,
        start_date="2026-01-01",
        frequency="monthly",
        description="Water delivery",
        amount="100.00",
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(await recurring_tools.get_recurring_expense_summary(ctx, NoArgs()))
        assert result["active_count"] == 2
        assert result["count_by_frequency"] == {"monthly": 2}
        assert result["estimated_monthly_commitment"] == "600.00"
