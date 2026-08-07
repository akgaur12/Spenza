"""Business logic for the `recurring_expenses` module.

Depends only on repositories + `ExpenseService` + shared infra — never on
FastAPI request/response objects — so it stays fully unit-testable.

Generation always goes through `ExpenseService.create_for_user`, never a
direct `ExpenseRepository`/`Expense(...)` call — the one rule this whole
module exists to uphold, so a generated expense is byte-for-byte what a
manually created one would be (same validation, same category rule, same
`expense.created` log) and needs zero special-casing in Dashboard,
Analytics, Reports, or Import/Export.
"""

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.core.timezone import APP_TIMEZONE, local_midnight_utc
from src.modules.expenses.models import Expense
from src.modules.expenses.schemas import ExpenseCreate
from src.modules.expenses.service import ExpenseService
from src.modules.recurring_expenses.enums import (
    Frequency,
    GenerationMode,
    RecurringExpenseSortField,
    RecurringExpenseStatus,
    SortOrder,
)
from src.modules.recurring_expenses.exceptions import (
    InvalidRecurringExpenseStatusError,
    RecurringExpenseNotActiveError,
    RecurringExpenseNotFoundError,
    RecurringExpenseNotPausedError,
    RecurringExpenseTerminalStateError,
)
from src.modules.recurring_expenses.models import RecurringExpense
from src.modules.recurring_expenses.recurrence import calculate_next_run_date
from src.modules.recurring_expenses.repository import RecurringExpenseRepository
from src.modules.recurring_expenses.schemas import RecurringExpenseCreate, RecurringExpenseUpdate
from src.modules.recurring_expenses.validators import validate_date_range
from src.modules.users.models import User
from src.modules.users.repository import UserRepository

logger = get_logger(__name__)

_TERMINAL_STATUSES = (RecurringExpenseStatus.COMPLETED, RecurringExpenseStatus.CANCELLED)


@dataclass(frozen=True, slots=True)
class RecurrenceRunSummary:
    """Outcome of one `process_due_recurrences()` pass — returned to the
    scheduler purely for logging, not persisted anywhere.
    """

    processed: int
    generated: int
    skipped_reminders: int
    completed: int
    failed: int


class RecurringExpenseService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._recurring = RecurringExpenseRepository(session)
        self._users = UserRepository(session)
        # Composed, not subclassed or reimplemented — every expense this
        # module creates goes through here.
        self._expenses = ExpenseService(session)

    # ── CRUD ──────────────────────────────────────────────────────────────

    async def create_for_user(self, user: User, data: RecurringExpenseCreate) -> RecurringExpense:
        category = await self._expenses.validate_category_for_user(data.category_id, user)
        recurring = self._recurring.create(
            user_id=user.id,
            category_id=category.id,
            description=data.description,
            amount=data.amount,
            frequency=data.frequency,
            generation_mode=data.generation_mode,
            start_date=data.start_date,
            end_date=data.end_date,
            # The first occurrence falls on `start_date` itself — that's
            # the date the user said this recurrence begins.
            next_run_date=data.start_date,
        )
        await self._recurring.flush()
        recurring.category = category
        logger.info(
            "recurring_expense.created",
            recurring_expense_id=str(recurring.id),
            user_id=str(user.id),
            frequency=str(data.frequency),
        )
        return recurring

    async def get_for_user(self, recurring_id: uuid.UUID, user: User) -> RecurringExpense:
        recurring = await self._recurring.get_by_id_for_user(recurring_id, user.id)
        if recurring is None:
            raise RecurringExpenseNotFoundError()
        return recurring

    async def list_for_user(
        self,
        user: User,
        *,
        status: RecurringExpenseStatus | None,
        frequency: Frequency | None,
        generation_mode: GenerationMode | None,
        search: str | None,
        sort_by: RecurringExpenseSortField,
        sort_order: SortOrder,
        page: int,
        page_size: int,
    ) -> tuple[list[RecurringExpense], int]:
        offset = (page - 1) * page_size
        return await self._recurring.list_for_user(
            user.id,
            status=status,
            frequency=frequency,
            generation_mode=generation_mode,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=offset,
            limit=page_size,
        )

    async def update_for_user(
        self, recurring_id: uuid.UUID, user: User, data: RecurringExpenseUpdate
    ) -> RecurringExpense:
        recurring = await self._get_owned(recurring_id, user)
        if recurring.status in _TERMINAL_STATUSES:
            raise RecurringExpenseTerminalStateError()

        updates = data.model_dump(exclude_unset=True)

        new_status = updates.pop("status", None)
        if new_status is not None:
            if new_status is not RecurringExpenseStatus.CANCELLED:
                raise InvalidRecurringExpenseStatusError()
            recurring.status = RecurringExpenseStatus.CANCELLED

        new_category_id = updates.pop("category_id", None)
        if new_category_id is not None:
            category = await self._expenses.validate_category_for_user(new_category_id, user)
            recurring.category_id = category.id
            recurring.category = category

        prospective_start = updates.get("start_date", recurring.start_date)
        prospective_end = updates.get("end_date", recurring.end_date)
        if "start_date" in updates or "end_date" in updates:
            validate_date_range(prospective_start, prospective_end)

        for field, value in updates.items():
            setattr(recurring, field, value)

        await self._recurring.flush()
        logger.info(
            "recurring_expense.updated",
            recurring_expense_id=str(recurring.id),
            user_id=str(user.id),
        )
        return recurring

    async def delete_for_user(self, recurring_id: uuid.UUID, user: User) -> None:
        recurring = await self._get_owned(recurring_id, user)
        await self._recurring.delete(recurring)
        await self._recurring.flush()
        logger.info(
            "recurring_expense.deleted",
            recurring_expense_id=str(recurring_id),
            user_id=str(user.id),
        )

    # ── Lifecycle actions ─────────────────────────────────────────────────

    async def pause_for_user(self, recurring_id: uuid.UUID, user: User) -> RecurringExpense:
        recurring = await self._get_owned(recurring_id, user)
        if recurring.status is not RecurringExpenseStatus.ACTIVE:
            raise RecurringExpenseNotActiveError()
        recurring.status = RecurringExpenseStatus.PAUSED
        await self._recurring.flush()
        logger.info("recurring_expense.paused", recurring_expense_id=str(recurring.id))
        return recurring

    async def resume_for_user(self, recurring_id: uuid.UUID, user: User) -> RecurringExpense:
        recurring = await self._get_owned(recurring_id, user)
        if recurring.status is not RecurringExpenseStatus.PAUSED:
            raise RecurringExpenseNotPausedError()
        recurring.status = RecurringExpenseStatus.ACTIVE
        await self._recurring.flush()
        logger.info("recurring_expense.resumed", recurring_expense_id=str(recurring.id))
        return recurring

    async def run_now_for_user(self, recurring_id: uuid.UUID, user: User) -> RecurringExpense:
        """Force-process the recurring expense's currently pending occurrence
        (`next_run_date`) right now, regardless of whether it's actually due
        yet — for testing, manual execution, or catching up a missed run.
        Uses `next_run_date` rather than "today" as the occurrence date, so
        a manual catch-up doesn't shift the recurrence's own cadence.
        """
        recurring = await self._get_owned(recurring_id, user)
        if recurring.status is not RecurringExpenseStatus.ACTIVE:
            raise RecurringExpenseNotActiveError()
        await self._process_one(recurring, user)
        return recurring

    # ── Scheduler entry point ───────────────────────────────────────────

    async def process_due_recurrences(self) -> RecurrenceRunSummary:
        """Everything the daily scheduler job does: load every `ACTIVE`
        recurring expense due today (across all users), and process each
        exactly once, each inside its own `SAVEPOINT` — so one row's
        failure rolls back only that row's changes and never half-applies
        or aborts the rest of the batch. A `SAVEPOINT` (not a full
        `session.rollback()`) matters here specifically: a full rollback
        expires *every* object the session has loaded, and this loop keeps
        working with the other rows already loaded via `find_due()` —
        touching their now-expired attributes outside `await` would raise
        `MissingGreenlet` from SQLAlchemy's asyncio extension. The caller
        (see `scheduler.py`) owns the session and commits once at the end.
        """
        today = datetime.now(APP_TIMEZONE).date()
        due = await self._recurring.find_due(today)
        if not due:
            return RecurrenceRunSummary(0, 0, 0, 0, 0)

        users_by_id = await self._users.get_many_by_id({r.user_id for r in due})

        generated = skipped_reminders = completed = failed = 0
        for recurring in due:
            user = users_by_id.get(recurring.user_id)
            if user is None:
                logger.error(
                    "recurring_expense.owner_missing", recurring_expense_id=str(recurring.id)
                )
                failed += 1
                continue
            try:
                pending_run_date = recurring.next_run_date
                async with self._session.begin_nested():
                    expense = await self._process_one(recurring, user)
                # Generating and completing aren't mutually exclusive — a
                # row can produce its final occurrence and complete in the
                # same pass, so both counters can increment together.
                if expense is not None:
                    generated += 1
                elif recurring.last_run_date == pending_run_date:
                    skipped_reminders += 1
                if recurring.status is RecurringExpenseStatus.COMPLETED:
                    completed += 1
            except Exception:
                logger.exception(
                    "recurring_expense.scheduler.item_failed",
                    recurring_expense_id=str(recurring.id),
                )
                failed += 1

        await self._session.commit()
        summary = RecurrenceRunSummary(
            processed=len(due),
            generated=generated,
            skipped_reminders=skipped_reminders,
            completed=completed,
            failed=failed,
        )
        logger.info("recurring_expense.scheduler.completed", **asdict(summary))
        return summary

    # ── Internals ─────────────────────────────────────────────────────────

    async def _get_owned(self, recurring_id: uuid.UUID, user: User) -> RecurringExpense:
        recurring = await self._recurring.get_by_id_for_user(recurring_id, user.id)
        if recurring is None:
            raise RecurringExpenseNotFoundError()
        return recurring

    async def _process_one(self, recurring: RecurringExpense, user: User) -> Expense | None:
        """One occurrence of `recurring`, dated `recurring.next_run_date`:
        generate (or skip, for a reminder) then advance the schedule.
        Idempotent per call site — the scheduler only ever calls this once
        per row per day, since advancing `next_run_date` past today is what
        makes a second same-day pass find nothing left `find_due()`.
        """
        run_date = recurring.next_run_date
        if recurring.end_date is not None and run_date > recurring.end_date:
            recurring.status = RecurringExpenseStatus.COMPLETED
            await self._recurring.flush()
            logger.info("recurring_expense.completed", recurring_expense_id=str(recurring.id))
            return None

        expense: Expense | None = None
        if recurring.generation_mode is GenerationMode.AUTO:
            expense = await self._expenses.create_for_user(
                user,
                ExpenseCreate(
                    category_id=recurring.category_id,
                    description=recurring.description,
                    amount=recurring.amount,
                    spent_at=local_midnight_utc(run_date),
                ),
            )
            logger.info(
                "recurring_expense.expense_generated",
                recurring_expense_id=str(recurring.id),
                expense_id=str(expense.id),
                user_id=str(user.id),
            )
        else:
            logger.info(
                "recurring_expense.reminder_skipped",
                recurring_expense_id=str(recurring.id),
                user_id=str(user.id),
            )

        recurring.last_run_date = run_date
        next_run_date = calculate_next_run_date(run_date, recurring.frequency)
        recurring.next_run_date = next_run_date
        if recurring.end_date is not None and next_run_date > recurring.end_date:
            recurring.status = RecurringExpenseStatus.COMPLETED
            logger.info("recurring_expense.completed", recurring_expense_id=str(recurring.id))

        await self._recurring.flush()
        return expense
