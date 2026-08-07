"""Unit tests for `RecurringExpenseRepository` — filtering, search, sort,
pagination, and the scheduler's `find_due` query. Users/categories are
seeded via the real HTTP API (so ids/ownership are exactly what a real
deployment would produce); the repository itself is exercised directly
against the resulting SQLite session, no HTTP involved for the assertions.
"""

import uuid
from datetime import date
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.recurring_expenses.enums import (
    Frequency,
    GenerationMode,
    RecurringExpenseSortField,
    RecurringExpenseStatus,
    SortOrder,
)
from src.modules.recurring_expenses.repository import RecurringExpenseRepository
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, category_id_by_name, login_user_a


async def _make_repo_and_user(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AsyncSession, RecurringExpenseRepository, uuid.UUID]:
    session = db_session_factory()
    users = UserRepository(session)
    user = await users.get_by_email(USER_A["email"])
    assert user is not None
    return session, RecurringExpenseRepository(session), user.id


async def test_create_and_get_by_id_for_user(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))

    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        recurring = repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Netflix",
            amount=Decimal("649.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        await repo.flush()
        await session.commit()
        recurring_id = recurring.id

    session, repo, _ = await _make_repo_and_user(db_session_factory)
    async with session:
        fetched = await repo.get_by_id_for_user(recurring_id, user_id)
        assert fetched is not None
        assert fetched.description == "Netflix"
        assert fetched.category.name == "Food"
        assert fetched.status == RecurringExpenseStatus.ACTIVE


async def test_get_by_id_for_user_is_none_for_another_owner(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        recurring = repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Netflix",
            amount=Decimal("649.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        await repo.flush()
        await session.commit()
        recurring_id = recurring.id

    session, repo, _ = await _make_repo_and_user(db_session_factory)
    async with session:
        fetched = await repo.get_by_id_for_user(recurring_id, uuid.uuid4())
        assert fetched is None


async def test_list_for_user_filters_by_status_frequency_and_generation_mode(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    travel_id = uuid.UUID(await category_id_by_name(client, "Travel"))

    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        active_monthly_auto = repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Netflix",
            amount=Decimal("649.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        weekly_reminder = repo.create(
            user_id=user_id,
            category_id=travel_id,
            description="Fuel reminder",
            amount=Decimal("50.00"),
            frequency=Frequency.WEEKLY,
            generation_mode=GenerationMode.REMINDER,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        await repo.flush()
        weekly_reminder.status = RecurringExpenseStatus.PAUSED
        await repo.flush()
        await session.commit()
        active_id = active_monthly_auto.id
        paused_id = weekly_reminder.id

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        items, total = await repo.list_for_user(uid, status=RecurringExpenseStatus.ACTIVE)
        assert total == 1
        assert items[0].id == active_id

        items, total = await repo.list_for_user(uid, frequency=Frequency.WEEKLY)
        assert total == 1
        assert items[0].id == paused_id

        items, total = await repo.list_for_user(uid, generation_mode=GenerationMode.REMINDER)
        assert total == 1
        assert items[0].id == paused_id

        items, total = await repo.list_for_user(uid)
        assert total == 2


async def test_list_for_user_search_matches_description_or_category_name(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    travel_id = uuid.UUID(await category_id_by_name(client, "Travel"))

    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Netflix Subscription",
            amount=Decimal("649.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        repo.create(
            user_id=user_id,
            category_id=travel_id,
            description="Monthly train pass",
            amount=Decimal("50.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        items, total = await repo.list_for_user(uid, search="netflix")
        assert total == 1
        assert items[0].description == "Netflix Subscription"

        items, total = await repo.list_for_user(uid, search="travel")
        assert total == 1
        assert items[0].description == "Monthly train pass"

        items, total = await repo.list_for_user(uid, search="monthly")
        assert total == 1
        assert items[0].description == "Monthly train pass"


async def test_list_for_user_sorts_by_amount(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))

    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        for amount in ("10.00", "30.00", "20.00"):
            repo.create(
                user_id=user_id,
                category_id=food_id,
                description=f"Item {amount}",
                amount=Decimal(amount),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
                end_date=None,
                next_run_date=date(2026, 8, 1),
            )
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        items, _ = await repo.list_for_user(
            uid, sort_by=RecurringExpenseSortField.AMOUNT, sort_order=SortOrder.ASC
        )
        assert [i.amount for i in items] == [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")]

        items, _ = await repo.list_for_user(
            uid, sort_by=RecurringExpenseSortField.AMOUNT, sort_order=SortOrder.DESC
        )
        assert [i.amount for i in items] == [Decimal("30.00"), Decimal("20.00"), Decimal("10.00")]


async def test_list_for_user_paginates(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))

    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        for i in range(5):
            repo.create(
                user_id=user_id,
                category_id=food_id,
                description=f"Item {i}",
                amount=Decimal("10.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
                end_date=None,
                next_run_date=date(2026, 8, 1),
            )
        await repo.flush()
        await session.commit()

    session, repo, uid = await _make_repo_and_user(db_session_factory)
    async with session:
        items, total = await repo.list_for_user(uid, offset=0, limit=2)
        assert total == 5
        assert len(items) == 2

        items, total = await repo.list_for_user(uid, offset=4, limit=2)
        assert total == 5
        assert len(items) == 1


async def test_find_due_returns_only_active_rows_due_today_across_users(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))

    session, repo, user_id = await _make_repo_and_user(db_session_factory)
    async with session:
        due_today = repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Due today",
            amount=Decimal("10.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 7),
        )
        due_in_past = repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Overdue",
            amount=Decimal("10.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 7, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        not_due_yet = repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Not due yet",
            amount=Decimal("10.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 9, 1),
            end_date=None,
            next_run_date=date(2026, 9, 1),
        )
        paused_but_due = repo.create(
            user_id=user_id,
            category_id=food_id,
            description="Paused",
            amount=Decimal("10.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 1),
            end_date=None,
            next_run_date=date(2026, 8, 1),
        )
        await repo.flush()
        paused_but_due.status = RecurringExpenseStatus.PAUSED
        await repo.flush()
        await session.commit()
        due_ids = {due_today.id, due_in_past.id}
        not_due_id = not_due_yet.id
        paused_id = paused_but_due.id

    session, repo, _ = await _make_repo_and_user(db_session_factory)
    async with session:
        due = await repo.find_due(date(2026, 8, 7))
        found_ids = {r.id for r in due}
        assert found_ids == due_ids
        assert not_due_id not in found_ids
        assert paused_id not in found_ids
