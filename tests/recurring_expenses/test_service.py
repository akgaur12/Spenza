"""Unit tests for `RecurringExpenseService`.

Most tests exercise the real `ExpenseService` end to end (same SQLite
session) to confirm a generated expense is indistinguishable from a
manually created one. A dedicated group at the bottom mocks
`ExpenseService` to verify the integration *contract* itself — that
generation always goes through `ExpenseService.create_for_user` and never
a direct repository insert — without re-testing `ExpenseService`'s own
internals (already covered by `tests/expenses`).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.timezone import APP_TIMEZONE
from src.modules.categories.exceptions import CategoryNotFoundError
from src.modules.expenses.models import Expense
from src.modules.expenses.schemas import ExpenseCreate
from src.modules.notifications.enums import NotificationType
from src.modules.notifications.models import Notification
from src.modules.recurring_expenses.enums import (
    Frequency,
    GenerationMode,
    RecurringExpenseStatus,
)
from src.modules.recurring_expenses.exceptions import (
    InvalidRecurringExpenseDateRangeError,
    InvalidRecurringExpenseStatusError,
    RecurringExpenseNotActiveError,
    RecurringExpenseNotFoundError,
    RecurringExpenseNotPausedError,
    RecurringExpenseTerminalStateError,
)
from src.modules.recurring_expenses.schemas import RecurringExpenseCreate, RecurringExpenseUpdate
from src.modules.recurring_expenses.service import RecurringExpenseService
from src.modules.users.models import User
from src.modules.users.repository import UserRepository
from tests.conftest import RecordingEmailBackend
from tests.import_export.helpers import USER_A, category_id_by_name, login_user_a


async def _get_user_and_service(
    db_session_factory: async_sessionmaker[AsyncSession], email: str = USER_A["email"]
) -> tuple[AsyncSession, RecurringExpenseService, User]:
    session = db_session_factory()
    users = UserRepository(session)
    user = await users.get_by_email(email)
    assert user is not None
    return session, RecurringExpenseService(session), user


# ── create ────────────────────────────────────────────────────────────────


async def test_create_sets_next_run_date_to_start_date_and_status_active(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))

    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix Subscription",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        assert recurring.status == RecurringExpenseStatus.ACTIVE
        assert recurring.next_run_date == date(2026, 8, 1)
        assert recurring.last_run_date is None
        assert recurring.category.name == "Food"


async def test_create_rejects_unknown_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        try:
            await service.create_for_user(
                user,
                RecurringExpenseCreate(
                    category_id=uuid.uuid4(),
                    description="Netflix",
                    amount=Decimal("649.00"),
                    frequency=Frequency.MONTHLY,
                    generation_mode=GenerationMode.AUTO,
                    start_date=date(2026, 8, 1),
                ),
            )
            raise AssertionError("expected CategoryNotFoundError")
        except CategoryNotFoundError:
            pass


async def test_create_rejects_end_date_before_start_date(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    try:
        RecurringExpenseCreate(
            category_id=food_id,
            description="Netflix",
            amount=Decimal("649.00"),
            frequency=Frequency.MONTHLY,
            generation_mode=GenerationMode.AUTO,
            start_date=date(2026, 8, 10),
            end_date=date(2026, 8, 1),
        )
        raise AssertionError("expected InvalidRecurringExpenseDateRangeError")
    except InvalidRecurringExpenseDateRangeError:
        pass


# ── get / ownership ──────────────────────────────────────────────────────


async def test_get_for_user_raises_not_found_for_unknown_id(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        try:
            await service.get_for_user(uuid.uuid4(), user)
            raise AssertionError("expected RecurringExpenseNotFoundError")
        except RecurringExpenseNotFoundError:
            pass


# ── update ───────────────────────────────────────────────────────────────


async def test_update_changes_fields_and_revalidates_category(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    travel_id = uuid.UUID(await category_id_by_name(client, "Travel"))

    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        updated = await service.update_for_user(
            recurring.id,
            user,
            RecurringExpenseUpdate(category_id=travel_id, amount=Decimal("699.00")),
        )
        assert updated.category_id == travel_id
        assert updated.amount == Decimal("699.00")


async def test_update_only_end_date_is_validated_against_existing_start_date(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Changing only `end_date` (not `start_date`) must still be checked
    against the record's existing `start_date` — the cross-field rule
    can't rely on both sides being present in the same request.
    """
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 10),
            ),
        )
        try:
            await service.update_for_user(
                recurring.id, user, RecurringExpenseUpdate(end_date=date(2026, 8, 1))
            )
            raise AssertionError("expected InvalidRecurringExpenseDateRangeError")
        except InvalidRecurringExpenseDateRangeError:
            pass

        # A valid end_date (>= the existing start_date) is accepted.
        updated = await service.update_for_user(
            recurring.id, user, RecurringExpenseUpdate(end_date=date(2026, 12, 31))
        )
        assert updated.end_date == date(2026, 12, 31)


async def test_update_rejects_status_other_than_cancelled(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        try:
            await service.update_for_user(
                recurring.id, user, RecurringExpenseUpdate(status=RecurringExpenseStatus.ACTIVE)
            )
            raise AssertionError("expected InvalidRecurringExpenseStatusError")
        except InvalidRecurringExpenseStatusError:
            pass


async def test_update_status_cancelled_is_allowed(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        updated = await service.update_for_user(
            recurring.id, user, RecurringExpenseUpdate(status=RecurringExpenseStatus.CANCELLED)
        )
        assert updated.status == RecurringExpenseStatus.CANCELLED


async def test_update_on_terminal_state_is_rejected(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        await service.update_for_user(
            recurring.id, user, RecurringExpenseUpdate(status=RecurringExpenseStatus.CANCELLED)
        )
        try:
            await service.update_for_user(
                recurring.id, user, RecurringExpenseUpdate(amount=Decimal("1.00"))
            )
            raise AssertionError("expected RecurringExpenseTerminalStateError")
        except RecurringExpenseTerminalStateError:
            pass


# ── delete ───────────────────────────────────────────────────────────────


async def test_delete_removes_the_row(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        recurring_id = recurring.id
        await service.delete_for_user(recurring_id, user)
        try:
            await service.get_for_user(recurring_id, user)
            raise AssertionError("expected RecurringExpenseNotFoundError")
        except RecurringExpenseNotFoundError:
            pass


# ── pause / resume ───────────────────────────────────────────────────────


async def test_pause_then_resume_round_trip(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        paused = await service.pause_for_user(recurring.id, user)
        assert paused.status == RecurringExpenseStatus.PAUSED

        resumed = await service.resume_for_user(recurring.id, user)
        assert resumed.status == RecurringExpenseStatus.ACTIVE


async def test_pause_twice_is_rejected(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        await service.pause_for_user(recurring.id, user)
        try:
            await service.pause_for_user(recurring.id, user)
            raise AssertionError("expected RecurringExpenseNotActiveError")
        except RecurringExpenseNotActiveError:
            pass


async def test_resume_without_pausing_is_rejected(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        try:
            await service.resume_for_user(recurring.id, user)
            raise AssertionError("expected RecurringExpenseNotPausedError")
        except RecurringExpenseNotPausedError:
            pass


# ── run now ──────────────────────────────────────────────────────────────


async def test_run_now_generates_an_expense_and_advances_schedule(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix Subscription",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        updated = await service.run_now_for_user(recurring.id, user)
        assert updated.last_run_date == date(2026, 8, 1)
        assert updated.next_run_date == date(2026, 9, 1)

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        expenses = result.scalars().all()
        assert len(expenses) == 1
        assert expenses[0].description == "Netflix Subscription"
        assert expenses[0].amount == Decimal("649.00")


async def test_run_now_on_paused_recurring_expense_is_rejected(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        await service.pause_for_user(recurring.id, user)
        try:
            await service.run_now_for_user(recurring.id, user)
            raise AssertionError("expected RecurringExpenseNotActiveError")
        except RecurringExpenseNotActiveError:
            pass


async def test_run_now_in_reminder_mode_never_creates_an_expense(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Rent reminder",
                amount=Decimal("15000.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.REMINDER,
                start_date=date(2026, 8, 1),
            ),
        )
        await service.run_now_for_user(recurring.id, user)

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        assert result.scalars().all() == []


async def test_run_now_past_end_date_marks_completed_without_generating(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Short-lived",
                amount=Decimal("10.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 1),
            ),
        )
        # First run consumes the only valid occurrence and, since the next
        # computed date (Sep 1) is past end_date, immediately completes.
        updated = await service.run_now_for_user(recurring.id, user)
        assert updated.status == RecurringExpenseStatus.COMPLETED

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        assert len(result.scalars().all()) == 1


# ── process_due_recurrences (scheduler entry point) ─────────────────────


async def test_process_due_recurrences_is_idempotent_within_a_single_day(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Running the batch twice on the same day must not create a second
    expense for a row already processed — the whole point of advancing
    `next_run_date` past today as part of processing it. Uses a `DAILY`
    recurrence starting exactly today: after one pass, `next_run_date`
    becomes tomorrow — the very next possible due date for this
    frequency — so a same-day rerun is guaranteed to find it not due,
    regardless of how long ago `start_date` was.
    """
    today = datetime.now(APP_TIMEZONE).date()
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=today,
            ),
        )

        first = await service.process_due_recurrences()
        assert first.generated == 1

        second = await service.process_due_recurrences()
        assert second.processed == 0
        assert second.generated == 0

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        assert len(result.scalars().all()) == 1


async def test_process_due_recurrences_reminder_mode_advances_without_generating(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Rent reminder",
                amount=Decimal("15000.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.REMINDER,
                start_date=date(2020, 1, 1),
            ),
        )

        summary = await service.process_due_recurrences()
        assert summary.processed == 1
        assert summary.generated == 0
        assert summary.skipped_reminders == 1

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        assert result.scalars().all() == []

        refreshed = await service.get_for_user(recurring.id, user)
        assert refreshed.last_run_date == date(2020, 1, 1)
        assert refreshed.next_run_date == date(2020, 1, 2)


async def test_process_due_recurrences_completes_past_end_date(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Short-lived",
                amount=Decimal("10.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 1),
            ),
        )

        summary = await service.process_due_recurrences()
        assert summary.generated == 1
        assert summary.completed == 1

        refreshed = await service.get_for_user(recurring.id, user)
        assert refreshed.status == RecurringExpenseStatus.COMPLETED

        # A second pass finds nothing due -> confirms it's really inactive now.
        second = await service.process_due_recurrences()
        assert second.processed == 0


async def test_process_one_completes_without_generating_when_end_date_retroactively_shortened(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A row can be left `ACTIVE` with `next_run_date` already past
    `end_date` if `end_date` is shortened *after* the schedule already
    advanced past it — the only way to reach that state, since creation
    and updates both reject an `end_date` before `start_date`, and a
    normal run always re-checks completion right after advancing. This
    covers `_process_one`'s early "already past end_date" branch,
    distinct from completing *while* generating a final occurrence.
    """
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 1, 1),
            ),
        )
        # Advances next_run_date to 2026-02-01, still ACTIVE (no end_date yet).
        await service.run_now_for_user(recurring.id, user)

        # Shortening end_date to before the now-current next_run_date is
        # accepted, since it's still >= the original start_date.
        await service.update_for_user(
            recurring.id, user, RecurringExpenseUpdate(end_date=date(2026, 1, 15))
        )

        updated = await service.run_now_for_user(recurring.id, user)
        assert updated.status == RecurringExpenseStatus.COMPLETED

        # Only the first run's expense exists — the second call generated nothing.
        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        assert len(result.scalars().all()) == 1


async def test_process_due_recurrences_isolates_a_failing_row_from_the_rest(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A row whose category was removed out from under it after creation
    (an organic failure — `ExpenseService.create_for_user` re-validates the
    category on every generation, not just at recurring-expense creation
    time) must not abort the rest of the batch.
    """
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        will_fail = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Will fail",
                amount=Decimal("10.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2020, 1, 1),
            ),
        )
        await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Will succeed",
                amount=Decimal("20.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2020, 1, 1),
            ),
        )
        # Simulate the category having been deleted after the recurring
        # expense was created — `create_for_user` re-checks it on every
        # generation, so this row will fail when the scheduler processes it.
        will_fail.category_id = uuid.uuid4()
        await service._recurring.flush()

        summary = await service.process_due_recurrences()
        assert summary.processed == 2
        assert summary.generated == 1
        assert summary.failed == 1

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        expenses = result.scalars().all()
        assert len(expenses) == 1
        assert expenses[0].description == "Will succeed"


async def test_process_due_recurrences_skips_row_with_missing_owner(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Extremely defensive: a recurring expense whose owning user can't be
    loaded (e.g. deleted out from under it in some other process) must be
    logged and skipped, never crash the whole batch.
    """
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2020, 1, 1),
            ),
        )

        service._users.get_many_by_id = AsyncMock(return_value={})  # type: ignore[method-assign]

        summary = await service.process_due_recurrences()
        assert summary.processed == 1
        assert summary.failed == 1
        assert summary.generated == 0


async def test_process_due_recurrences_skips_paused_rows(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2020, 1, 1),
            ),
        )
        await service.pause_for_user(recurring.id, user)

        summary = await service.process_due_recurrences()
        assert summary.processed == 0

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        assert result.scalars().all() == []


async def test_process_due_recurrences_returns_zeroed_summary_when_nothing_due(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    session, service, _user = await _get_user_and_service(db_session_factory)
    async with session:
        summary = await service.process_due_recurrences()
        assert summary.processed == 0
        assert summary.generated == 0
        assert summary.skipped_reminders == 0
        assert summary.completed == 0
        assert summary.failed == 0


# ── integration boundary: generation must go through ExpenseService ────


async def test_run_now_delegates_generation_to_expense_service(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Mocks `ExpenseService` to verify the integration contract itself —
    that a generated occurrence goes through `create_for_user` with the
    recurring expense's own fields, never a direct `ExpenseRepository`
    call — without re-exercising `ExpenseService`'s own internals.
    """
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix Subscription",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )

        fake_expense = AsyncMock()
        fake_expense.id = uuid.uuid4()
        mock_expenses = AsyncMock()
        mock_expenses.create_for_user = AsyncMock(return_value=fake_expense)
        service._expenses = mock_expenses

        await service.run_now_for_user(recurring.id, user)

        mock_expenses.create_for_user.assert_awaited_once()
        called_user, called_data = mock_expenses.create_for_user.await_args.args
        assert called_user is user
        assert isinstance(called_data, ExpenseCreate)
        assert called_data.category_id == food_id
        assert called_data.description == "Netflix Subscription"
        assert called_data.amount == Decimal("649.00")


async def test_scheduler_reminder_mode_never_calls_expense_service(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Rent reminder",
                amount=Decimal("15000.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.REMINDER,
                start_date=date(2020, 1, 1),
            ),
        )

        mock_expenses = AsyncMock()
        service._expenses = mock_expenses

        await service.process_due_recurrences()

        mock_expenses.create_for_user.assert_not_awaited()


# ── notifications ─────────────────────────────────────────────────────────


async def test_run_now_creates_a_recurring_expense_created_notification(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix Subscription",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )
        await service.run_now_for_user(recurring.id, user)

        notifications = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.user_id == user.id,
                        Notification.type == NotificationType.RECURRING_EXPENSE_CREATED,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification.title == "Recurring Expense Created"
        assert notification.message == "Netflix Subscription — ₹649.00 was added automatically."
        assert notification.payload == {"amount": "649.00", "category_name": "Food"}


async def test_run_now_in_reminder_mode_does_not_create_a_notification(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Rent reminder",
                amount=Decimal("15000.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.REMINDER,
                start_date=date(2026, 8, 1),
            ),
        )
        await service.run_now_for_user(recurring.id, user)

        notifications = (
            (await session.execute(select(Notification).where(Notification.user_id == user.id)))
            .scalars()
            .all()
        )
        assert notifications == []


async def test_process_due_recurrences_creates_a_notification_for_the_generated_expense(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    today = datetime.now(APP_TIMEZONE).date()
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=today,
            ),
        )

        summary = await service.process_due_recurrences()
        assert summary.generated == 1

        notifications = (
            (
                await session.execute(
                    select(Notification).where(
                        Notification.user_id == user.id,
                        Notification.type == NotificationType.RECURRING_EXPENSE_CREATED,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(notifications) == 1


async def test_notification_failure_does_not_block_run_now_expense_generation(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        recurring = await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix Subscription",
                amount=Decimal("649.00"),
                frequency=Frequency.MONTHLY,
                generation_mode=GenerationMode.AUTO,
                start_date=date(2026, 8, 1),
            ),
        )

        with patch(
            "src.modules.notifications.service.NotificationService.send",
            new=AsyncMock(side_effect=RuntimeError("simulated notification-layer failure")),
        ):
            updated = await service.run_now_for_user(recurring.id, user)

        assert updated.last_run_date == date(2026, 8, 1)
        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        expenses = result.scalars().all()
        assert len(expenses) == 1
        assert expenses[0].description == "Netflix Subscription"


async def test_notification_failure_does_not_roll_back_the_scheduler_row(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The scheduler wraps each row in its own `SAVEPOINT` — an unhandled
    notification failure would roll that row's expense + schedule
    advancement back right along with it, and mark the row `failed` rather
    than `generated`. This proves `_notify_expense_created`'s try/except
    keeps that from happening.
    """
    today = datetime.now(APP_TIMEZONE).date()
    await login_user_a(client, email_backend)
    food_id = uuid.UUID(await category_id_by_name(client, "Food"))
    session, service, user = await _get_user_and_service(db_session_factory)
    async with session:
        await service.create_for_user(
            user,
            RecurringExpenseCreate(
                category_id=food_id,
                description="Netflix",
                amount=Decimal("649.00"),
                frequency=Frequency.DAILY,
                generation_mode=GenerationMode.AUTO,
                start_date=today,
            ),
        )

        with patch(
            "src.modules.notifications.service.NotificationService.send",
            new=AsyncMock(side_effect=RuntimeError("simulated notification-layer failure")),
        ):
            summary = await service.process_due_recurrences()

        assert summary.generated == 1
        assert summary.failed == 0

        result = await session.execute(select(Expense).where(Expense.user_id == user.id))
        assert len(result.scalars().all()) == 1
