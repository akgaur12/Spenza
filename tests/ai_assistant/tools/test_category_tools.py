"""Tests for the category tools: correctness, user isolation (a user's own
custom category never leaks to another user), and `args_schema` safety.
"""

import json
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.ai_assistant.tools import categories as category_tools
from src.modules.ai_assistant.tools.context import ToolContext
from src.modules.ai_assistant.tools.schemas import CompareCategoriesArgs, GetCategoriesArgs
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
    for schema in (GetCategoriesArgs, CompareCategoriesArgs):
        assert "user" not in schema.model_fields
        assert "user_id" not in schema.model_fields


async def test_get_categories_includes_system_and_excludes_other_users_custom(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    create_response = await client.post("/api/v1/categories", json={"name": "Side Hustle"})
    assert create_response.status_code == 201, create_response.text

    await login_user_b(client, email_backend)

    async with db_session_factory() as session:
        user_b = await get_user(session, USER_B_SIGNUP["email"])
        ctx_b = ToolContext(user=user_b, session=session)

        result = json.loads(
            await category_tools.get_categories(ctx_b, GetCategoriesArgs(search=None))
        )
        names = [c["name"] for c in result["categories"]]
        assert "Food" in names  # system category, visible to everyone
        assert "Side Hustle" not in names  # user A's private category

        user_a = await get_user(session, USER_A_SIGNUP["email"])
        ctx_a = ToolContext(user=user_a, session=session)
        result_a = json.loads(
            await category_tools.get_categories(ctx_a, GetCategoriesArgs(search=None))
        )
        assert "Side Hustle" in [c["name"] for c in result_a["categories"]]


async def test_compare_categories(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 3, 5, tzinfo=UTC), amount="300.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=datetime(2026, 2, 5, tzinfo=UTC), amount="100.00"
    )

    async with db_session_factory() as session:
        user = await get_user(session, USER_A_SIGNUP["email"])
        ctx = ToolContext(user=user, session=session)

        result = json.loads(
            await category_tools.compare_categories(
                ctx, CompareCategoriesArgs(start_date=MARCH_START, end_date=MARCH_END)
            )
        )
        food_row = next(c for c in result["categories"] if c["name"] == "Food")
        assert food_row["current_total"] == "300.00"
        assert food_row["previous_total"] == "100.00"
        assert food_row["difference"] == "200.00"
