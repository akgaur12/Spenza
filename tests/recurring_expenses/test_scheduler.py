"""Unit tests for `recurring_expenses.scheduler`'s registration/lifecycle.

Doesn't exercise `run_due_recurrences_job` itself — that function opens a
session via the module-level `AsyncSessionLocal`, bound to the app's real
configured `DATABASE_URL`, not the per-test SQLite database — so the job
*body*'s behavior (generation, idempotency, completion) is covered instead
by `test_service.py`'s `process_due_recurrences` tests, which use the same
logic against the test database directly.
"""

import asyncio

from apscheduler.triggers.cron import CronTrigger

from src.core.app_config import settings
from src.modules.recurring_expenses.scheduler import (
    JOB_ID,
    shutdown_scheduler,
    start_scheduler,
)


async def test_start_scheduler_registers_the_daily_job() -> None:
    scheduler = start_scheduler()
    try:
        job = scheduler.get_job(JOB_ID)
        assert job is not None
        assert isinstance(job.trigger, CronTrigger)
        assert job.next_run_time is not None
    finally:
        shutdown_scheduler()
        await asyncio.sleep(0)


async def test_start_scheduler_uses_configured_run_time() -> None:
    scheduler = start_scheduler()
    try:
        job = scheduler.get_job(JOB_ID)
        assert job is not None
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields["hour"] == str(settings.RECURRING_EXPENSE_SCHEDULER_HOUR)
        assert fields["minute"] == str(settings.RECURRING_EXPENSE_SCHEDULER_MINUTE)
    finally:
        shutdown_scheduler()
        await asyncio.sleep(0)


async def test_shutdown_scheduler_stops_it() -> None:
    scheduler = start_scheduler()
    shutdown_scheduler()
    await asyncio.sleep(0.05)
    assert scheduler.running is False


async def test_shutdown_scheduler_is_a_no_op_when_never_started() -> None:
    # Ensure a clean slate, then call shutdown with nothing running.
    shutdown_scheduler()
    shutdown_scheduler()  # must not raise
