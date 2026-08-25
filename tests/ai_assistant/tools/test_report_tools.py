"""Tests for the report-summary tool: correctness against seeded data,
user isolation, and `args_schema` safety. This tool deliberately composes
`DashboardService`/`AnalyticsService` rather than calling `ReportService`
(see `src.modules.ai_assistant.tools.reports`'s docstring) — these tests
guard the shape of that composition.
"""

import json
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.ai_assistant.tools import reports as report_tools
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.schemas import GetReportSummaryArgs
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
    assert "user" not in GetReportSummaryArgs.model_fields
    assert "user_id" not in GetReportSummaryArgs.model_fields


async def test_get_report_summary_totals_and_top_category(
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
    await create_expense(
        client,
        category_id=food_id,
        spent_at=datetime(2026, 2, 6, tzinfo=UTC),
        amount="500.00",
        description="Last month's groceries",
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(
            await report_tools.get_report_summary(
                ctx, GetReportSummaryArgs(start_date=MARCH_START, end_date=MARCH_END)
            )
        )
        assert result["total_spending"] == "1000.00"
        assert result["top_category"] == "Travel"
        assert result["previous_period"]["total_spending"] == "500.00"
        assert result["difference_vs_previous_period"] == "500.00"
        assert {c["name"] for c in result["top_categories"]} == {"Food", "Travel"}


async def test_get_report_summary_isolated_between_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 3, 5, tzinfo=UTC), amount="10.00"
    )

    await login_user_b(client, email_backend)
    b_food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=b_food_id, spent_at=datetime(2026, 3, 5, tzinfo=UTC), amount="7777.00"
    )

    async with db_session_factory() as session:
        user_b = await get_user(session, USER_B_SIGNUP["email"])
        ctx_b = ToolContext(user=user_b, session=session)
        result_b = json.loads(
            await report_tools.get_report_summary(
                ctx_b, GetReportSummaryArgs(start_date=MARCH_START, end_date=MARCH_END)
            )
        )
        assert result_b["total_spending"] == "7777.00"
