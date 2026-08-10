"""APScheduler wiring for the daily recurring-expense job.

Started/stopped from `src.lifespan` at application startup/shutdown — the
job itself opens its own short-lived `AsyncSession` per run, the same
pattern `src.core.cleanup.run_cleanup_job` already uses for its daily
sweep, so this doesn't hold a request-scoped session across a whole day. An
exception here must never stop future runs (see `run_due_recurrences_job`);
per-row failures are already isolated inside
`RecurringExpenseService.process_due_recurrences`.
"""

from dataclasses import asdict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.app_config import settings
from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.core.timezone import APP_TIMEZONE
from src.modules.recurring_expenses.service import RecurringExpenseService

logger = get_logger(__name__)

JOB_ID = "recurring_expenses.process_due"

_scheduler: AsyncIOScheduler | None = None


async def run_due_recurrences_job() -> None:
    """The job body — also directly callable (tests, a manual admin
    trigger) without going through APScheduler at all.
    """
    async with AsyncSessionLocal() as session:
        try:
            service = RecurringExpenseService(session)
            summary = await service.process_due_recurrences()
            logger.info("recurring_expense.scheduler.run", **asdict(summary))
        except Exception:
            logger.exception("recurring_expense.scheduler.failed")


def start_scheduler() -> AsyncIOScheduler:
    """Create, configure, and start the module-level scheduler singleton.
    Idempotent-ish: calling it again after a prior `shutdown_scheduler()`
    creates a fresh instance, matching `src.lifespan`'s one-per-process-
    lifetime usage.
    """
    global _scheduler
    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
    scheduler.add_job(
        run_due_recurrences_job,
        trigger=CronTrigger(
            hour=settings.RECURRING_EXPENSE_SCHEDULER_HOUR,
            minute=settings.RECURRING_EXPENSE_SCHEDULER_MINUTE,
            timezone=APP_TIMEZONE,
        ),
        id=JOB_ID,
        replace_existing=True,
        # A missed fire (process was down at 1am) still runs, as long as
        # it's noticed within an hour of when it should have fired —
        # beyond that it's skipped rather than firing hours late.
        misfire_grace_time=3600,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "recurring_expense.scheduler.started",
        hour=settings.RECURRING_EXPENSE_SCHEDULER_HOUR,
        minute=settings.RECURRING_EXPENSE_SCHEDULER_MINUTE,
    )
    return scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler without waiting for an in-flight job — mirrors
    `src.lifespan`'s cancel-then-`CancelledError`-suppress shutdown for the
    OTP cleanup task, so process shutdown is never blocked on this.
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("recurring_expense.scheduler.stopped")
