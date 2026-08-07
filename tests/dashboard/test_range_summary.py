"""Unit tests for `DashboardService.get_range_summary` — the generalization
of `get_summary()`'s fixed "this month"/"this year" windows to an arbitrary
`[start, end)` range, added for the `reports` module (which needs "this
month"-style metrics for a period that isn't anchored to "now").
"""

from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.timezone import local_midnight_utc
from src.modules.dashboard.service import DashboardService
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, category_id_by_name, create_expense, login_user_a


async def test_range_summary_for_an_arbitrary_past_period(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(
        client,
        category_id=food_id,
        description="Cake",
        amount="100.00",
        spent_at="2025-07-10T00:00:00+05:30",
    )
    await create_expense(
        client,
        category_id=food_id,
        description="Coffee",
        amount="50.00",
        spent_at="2025-07-20T00:00:00+05:30",
    )

    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email(USER_A["email"])
        assert user is not None
        service = DashboardService(session)
        summary = await service.get_range_summary(
            user,
            local_midnight_utc(date(2025, 7, 1)),
            local_midnight_utc(date(2025, 8, 1)),
            31,
        )

    assert summary.total == Decimal("150.00")
    assert summary.expense_count == 2
    assert summary.average_expense == Decimal("75.00")
    assert summary.daily_average == Decimal("4.84")
    assert summary.top_category is not None
    assert summary.top_category.name == "Food"
    assert summary.largest_expense is not None
    assert summary.largest_expense.description == "Cake"


async def test_range_summary_with_no_expenses_is_zeroed(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)

    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email(USER_A["email"])
        assert user is not None
        service = DashboardService(session)
        summary = await service.get_range_summary(
            user,
            local_midnight_utc(date(2025, 7, 1)),
            local_midnight_utc(date(2025, 8, 1)),
            31,
        )

    assert summary.total == Decimal("0.00")
    assert summary.expense_count == 0
    assert summary.top_category is None
    assert summary.largest_expense is None


async def test_range_summary_zero_span_days_does_not_divide_by_zero(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)

    async with db_session_factory() as session:
        users = UserRepository(session)
        user = await users.get_by_email(USER_A["email"])
        assert user is not None
        service = DashboardService(session)
        summary = await service.get_range_summary(
            user,
            local_midnight_utc(date(2025, 7, 1)),
            local_midnight_utc(date(2025, 7, 1)),
            0,
        )

    assert summary.daily_average == Decimal("0.00")
