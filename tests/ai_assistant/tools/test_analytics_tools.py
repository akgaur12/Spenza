"""Tests for the analytics tools: correctness against seeded data, user
isolation, and that no tool's `args_schema` exposes `user`/`user_id`.
"""

import json
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.ai_assistant.tools import analytics as analytics_tools
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.schemas import (
    ComparePeriodsArgs,
    DateRangeArgs,
    GetCategorySpendingArgs,
    GetLargestExpensesArgs,
    GetSpendingTrendsArgs,
    GetTopCategoriesArgs,
)
from src.modules.analytics.schemas import TrendInterval
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

MARCH_START = datetime(2026, 3, 1, tzinfo=UTC).date()
MARCH_END = datetime(2026, 3, 31, tzinfo=UTC).date()


def test_no_tool_args_schema_exposes_user() -> None:
    for schema in (
        DateRangeArgs,
        GetSpendingTrendsArgs,
        GetCategorySpendingArgs,
        GetTopCategoriesArgs,
        GetLargestExpensesArgs,
        ComparePeriodsArgs,
    ):
        assert "user" not in schema.model_fields
        assert "user_id" not in schema.model_fields


async def test_get_category_spending_and_top_categories(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    travel_id = await category_id_by_name(client, "Travel")
    await create_expense(
        client,
        category_id=food_id,
        spent_at=datetime(2026, 3, 5, tzinfo=UTC),
        amount="100.00",
        description="Lunch",
    )
    await create_expense(
        client,
        category_id=travel_id,
        spent_at=datetime(2026, 3, 6, tzinfo=UTC),
        amount="900.00",
        description="Flight",
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        breakdown = json.loads(
            await analytics_tools.get_category_spending(
                ctx, GetCategorySpendingArgs(start_date=MARCH_START, end_date=MARCH_END)
            )
        )
        assert breakdown["total_spending"] == "1000.00"

        top = json.loads(
            await analytics_tools.get_top_categories(
                ctx, GetTopCategoriesArgs(start_date=MARCH_START, end_date=MARCH_END, limit=1)
            )
        )
        assert top["top_categories"] == [{"name": "Travel", "total": "900.00", "percentage": 90.0}]


async def test_get_largest_expenses(
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
        amount="50.00",
        description="Snack",
    )
    await create_expense(
        client,
        category_id=food_id,
        spent_at=datetime(2026, 3, 6, tzinfo=UTC),
        amount="700.00",
        description="Feast",
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(
            await analytics_tools.get_largest_expenses(
                ctx, GetLargestExpensesArgs(start_date=MARCH_START, end_date=MARCH_END, limit=1)
            )
        )
        assert len(result["largest_expenses"]) == 1
        assert result["largest_expenses"][0]["description"] == "Feast"


async def test_get_spending_trends_daily(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 3, 5, tzinfo=UTC), amount="120.00"
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(
            await analytics_tools.get_spending_trends(
                ctx,
                GetSpendingTrendsArgs(
                    interval=TrendInterval.DAILY, start_date=MARCH_START, end_date=MARCH_END
                ),
            )
        )
        assert result["total_spending"] == "120.00"
        matching = [p for p in result["data"] if p["period"] == "2026-03-05"]
        assert matching
        assert matching[0]["total"] == "120.00"


async def test_compare_periods_isolated_between_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 3, 10, tzinfo=UTC), amount="200.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 2, 10, tzinfo=UTC), amount="100.00"
    )

    await login_user_b(client, email_backend)
    b_food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=b_food_id, spent_at=datetime(2026, 3, 10, tzinfo=UTC), amount="9999.00"
    )

    async with db_session_factory() as session:
        user_a = await get_user(session, USER_A_SIGNUP["email"])
        ctx_a = ToolContext(user=user_a, session=session)
        result = json.loads(
            await analytics_tools.compare_periods(
                ctx_a, ComparePeriodsArgs(start_date=MARCH_START, end_date=MARCH_END)
            )
        )
        assert result["current_period"]["total"] == "200.00"
        assert result["previous_period"]["total"] == "100.00"
        assert result["difference"] == "100.00"
        assert result["trend"] == "up"

        user_b = await get_user(session, USER_B_SIGNUP["email"])
        ctx_b = ToolContext(user=user_b, session=session)
        result_b = json.loads(
            await analytics_tools.compare_periods(
                ctx_b, ComparePeriodsArgs(start_date=MARCH_START, end_date=MARCH_END)
            )
        )
        assert result_b["current_period"]["total"] == "9999.00"
