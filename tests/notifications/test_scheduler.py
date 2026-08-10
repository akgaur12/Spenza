"""Unit tests for `notifications.scheduler`'s registration/lifecycle.

Mirrors `tests.recurring_expenses.test_scheduler` — only registration is
tested here; each job's *body* is covered directly against the test
database by `test_report_jobs.py` / `test_notification_jobs.py` /
`tests/core/test_cleanup.py`, since the job wrappers open a session via the
module-level `AsyncSessionLocal` bound to the real `DATABASE_URL`, not the
per-test SQLite database.
"""

import asyncio

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.core.app_config import settings
from src.modules.notifications.scheduler import (
    CLEANUP_JOB_ID,
    MONTHLY_REPORT_JOB_ID,
    NOTIFICATION_EMAIL_JOB_ID,
    YEARLY_REPORT_JOB_ID,
    shutdown_scheduler,
    start_scheduler,
)


async def test_start_scheduler_registers_all_four_jobs() -> None:
    scheduler = start_scheduler()
    try:
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert job_ids == {
            NOTIFICATION_EMAIL_JOB_ID,
            MONTHLY_REPORT_JOB_ID,
            YEARLY_REPORT_JOB_ID,
            CLEANUP_JOB_ID,
        }
        for job in scheduler.get_jobs():
            assert job.next_run_time is not None
    finally:
        shutdown_scheduler()
        await asyncio.sleep(0)


async def test_notification_email_job_uses_the_configured_interval() -> None:
    scheduler = start_scheduler()
    try:
        job = scheduler.get_job(NOTIFICATION_EMAIL_JOB_ID)
        assert job is not None
        assert isinstance(job.trigger, IntervalTrigger)
        assert job.trigger.interval.total_seconds() == (
            settings.NOTIFICATION_EMAIL_JOB_INTERVAL_MINUTES * 60
        )
    finally:
        shutdown_scheduler()
        await asyncio.sleep(0)


async def test_report_jobs_use_cron_triggers_at_configured_times() -> None:
    scheduler = start_scheduler()
    try:
        monthly = scheduler.get_job(MONTHLY_REPORT_JOB_ID)
        yearly = scheduler.get_job(YEARLY_REPORT_JOB_ID)
        cleanup = scheduler.get_job(CLEANUP_JOB_ID)
        assert monthly is not None
        assert isinstance(monthly.trigger, CronTrigger)
        assert yearly is not None
        assert isinstance(yearly.trigger, CronTrigger)
        assert cleanup is not None
        assert isinstance(cleanup.trigger, CronTrigger)

        monthly_fields = {f.name: str(f) for f in monthly.trigger.fields}
        assert monthly_fields["hour"] == str(settings.MONTHLY_REPORT_SCHEDULER_HOUR)
        assert monthly_fields["minute"] == str(settings.MONTHLY_REPORT_SCHEDULER_MINUTE)
    finally:
        shutdown_scheduler()
        await asyncio.sleep(0)


async def test_shutdown_scheduler_stops_it() -> None:
    scheduler = start_scheduler()
    shutdown_scheduler()
    await asyncio.sleep(0.05)
    assert scheduler.running is False


async def test_shutdown_scheduler_is_a_no_op_when_never_started() -> None:
    shutdown_scheduler()
    shutdown_scheduler()  # must not raise
