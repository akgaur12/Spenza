"""Tests for the expense tools: correctness against seeded data, user
isolation, and that no tool's `args_schema` ever exposes `user`/`user_id`.
"""

import json
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.ai_assistant.tools import expenses as expense_tools
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.schemas import (
    GetExpenseArgs,
    GetExpensesArgs,
    GetTotalSpendingArgs,
    SearchExpensesArgs,
)
from tests.ai_assistant.helpers import (
    USER_A_SIGNUP,
    USER_B_SIGNUP,
    category_id_by_name,
    create_expense,
    get_user,
    login_user_a,
    login_user_b,
)
from tests.conftest import RecordingEmailBackend


def test_no_tool_args_schema_exposes_user() -> None:
    for schema in (GetExpensesArgs, SearchExpensesArgs, GetExpenseArgs, GetTotalSpendingArgs):
        assert "user" not in schema.model_fields
        assert "user_id" not in schema.model_fields


async def test_get_expenses_filters_by_category_and_date(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    travel_id = await category_id_by_name(client, "Travel")
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 3, 5, tzinfo=UTC), description="Lunch"
    )
    await create_expense(
        client,
        category_id=travel_id,
        spent_at=datetime(2026, 3, 6, tzinfo=UTC),
        description="Flight",
        amount="5000.00",
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(
            await expense_tools.get_expenses(
                ctx, GetExpensesArgs(category="Food", start_date=None, end_date=None)
            )
        )
        assert result["total_matching"] == 1
        assert result["expenses"][0]["description"] == "Lunch"
        assert result["category_filter_matched"] == "Food"


async def test_search_expenses_matches_description(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        spent_at=datetime(2026, 3, 5, tzinfo=UTC),
        description="Pizza night",
    )
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 3, 6, tzinfo=UTC), description="Coffee"
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(
            await expense_tools.search_expenses(
                ctx, SearchExpensesArgs(search_term="pizza", start_date=None, end_date=None)
            )
        )
        assert result["total_matching"] == 1
        assert result["expenses"][0]["description"] == "Pizza night"


async def test_get_expense_not_found_is_graceful(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(
            await expense_tools.get_expense(
                ctx, GetExpenseArgs(expense_id="00000000-0000-0000-0000-000000000000")
            )
        )
        assert result["found"] is False


async def test_get_total_spending_isolated_between_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        spent_at=datetime(2026, 3, 5, tzinfo=UTC),
        description="User A lunch",
        amount="300.00",
    )

    await login_user_b(client, email_backend)
    b_food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=b_food_id,
        spent_at=datetime(2026, 3, 5, tzinfo=UTC),
        description="User B lunch",
        amount="999.00",
    )

    async with db_session_factory() as session:
        user_a = await get_user(session, USER_A_SIGNUP["email"])
        ctx_a = ToolContext(user=user_a, session=session)
        result_a = json.loads(
            await expense_tools.get_total_spending(
                ctx_a,
                GetTotalSpendingArgs(
                    start_date=datetime(2026, 3, 1, tzinfo=UTC).date(),
                    end_date=datetime(2026, 3, 31, tzinfo=UTC).date(),
                ),
            )
        )
        assert result_a["total"] == "300.00"

        user_b = await get_user(session, USER_B_SIGNUP["email"])
        ctx_b = ToolContext(user=user_b, session=session)
        result_b = json.loads(
            await expense_tools.get_total_spending(
                ctx_b,
                GetTotalSpendingArgs(
                    start_date=datetime(2026, 3, 1, tzinfo=UTC).date(),
                    end_date=datetime(2026, 3, 31, tzinfo=UTC).date(),
                ),
            )
        )
        assert result_b["total"] == "999.00"
