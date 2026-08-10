"""APScheduler wiring for Phase 11B's scheduled email delivery jobs.

A separate `AsyncIOScheduler` instance from `recurring_expenses.scheduler`
— each module owns its own jobs and lifecycle, started/stopped
independently from `src.lifespan`, mirroring that module's pattern exactly:
each job opens its own short-lived `AsyncSession` per run (see the
`jobs/*.py` wrappers), and a failure in one run must never stop future runs
or crash the process.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.core.app_config import settings
from src.core.cleanup import run_cleanup_job
from src.core.logger import get_logger
from src.core.timezone import APP_TIMEZONE
from src.modules.notifications.jobs.notification_jobs import run_notification_email_job
from src.modules.notifications.jobs.report_jobs import (
    run_monthly_report_job,
    run_yearly_report_job,
)

logger = get_logger(__name__)

NOTIFICATION_EMAIL_JOB_ID = "notifications.deliver_pending_emails"
MONTHLY_REPORT_JOB_ID = "notifications.monthly_report"
YEARLY_REPORT_JOB_ID = "notifications.yearly_report"
CLEANUP_JOB_ID = "maintenance.cleanup"

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler:
    """Create, configure, and start the module-level scheduler singleton.
    Idempotent-ish: calling it again after a prior `shutdown_scheduler()`
    creates a fresh instance, matching `src.lifespan`'s one-per-process-
    lifetime usage.
    """
    global _scheduler
    scheduler = AsyncIOScheduler(timezone=APP_TIMEZONE)
    scheduler.add_job(
        run_notification_email_job,
        trigger=IntervalTrigger(minutes=settings.NOTIFICATION_EMAIL_JOB_INTERVAL_MINUTES),
        id=NOTIFICATION_EMAIL_JOB_ID,
        replace_existing=True,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        run_monthly_report_job,
        trigger=CronTrigger(
            hour=settings.MONTHLY_REPORT_SCHEDULER_HOUR,
            minute=settings.MONTHLY_REPORT_SCHEDULER_MINUTE,
            timezone=APP_TIMEZONE,
        ),
        id=MONTHLY_REPORT_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_yearly_report_job,
        trigger=CronTrigger(
            hour=settings.YEARLY_REPORT_SCHEDULER_HOUR,
            minute=settings.YEARLY_REPORT_SCHEDULER_MINUTE,
            timezone=APP_TIMEZONE,
        ),
        id=YEARLY_REPORT_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Not notifications-specific despite living on this scheduler: covers
    # email_otps, notifications, notification_delivery_logs, import_sessions,
    # and refresh_sessions — see `src.core.cleanup`. Reuses this scheduler
    # rather than standing up a dedicated one, since it's already the
    # process's daily-housekeeping scheduler (reports run here too).
    scheduler.add_job(
        run_cleanup_job,
        trigger=CronTrigger(
            hour=settings.NOTIFICATION_CLEANUP_SCHEDULER_HOUR,
            minute=settings.NOTIFICATION_CLEANUP_SCHEDULER_MINUTE,
            timezone=APP_TIMEZONE,
        ),
        id=CLEANUP_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("notifications.scheduler.started")
    return scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler without waiting for an in-flight job — mirrors
    `src.lifespan`'s cancel-then-suppress shutdown, so process shutdown is
    never blocked on this.
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("notifications.scheduler.stopped")
