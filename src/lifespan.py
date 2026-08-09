"""Application startup/shutdown hooks."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from src.core.app_config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.logger import get_logger
from src.modules.notifications.scheduler import (
    shutdown_scheduler as shutdown_notification_scheduler,
)
from src.modules.notifications.scheduler import start_scheduler as start_notification_scheduler
from src.modules.recurring_expenses.scheduler import shutdown_scheduler, start_scheduler
from src.modules.users.service import cleanup_expired_otps

logger = get_logger(__name__)


async def _otp_cleanup_loop() -> None:
    """Delete stale `email_otps` rows every `OTP_CLEANUP_INTERVAL_SECONDS`
    for the life of the process.

    Runs independently per worker process — there's no cross-process lock —
    which is safe since deleting already-gone rows is a no-op, just mildly
    redundant with more than one worker. See `scripts/cleanup_otps.py` for
    the external-scheduler alternative that doesn't depend on process uptime.
    """
    while True:
        await asyncio.sleep(settings.OTP_CLEANUP_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as session:
                deleted = await cleanup_expired_otps(session)
            logger.info("otp_cleanup.completed", deleted=deleted)
        except Exception:
            logger.exception("otp_cleanup.failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logger.info(
        "Starting application",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.APP_ENV,
    )

    db_url = engine.url
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info(
        "Database connection verified",
        driver=db_url.drivername,
        host=db_url.host,
        port=db_url.port,
        database=db_url.database,
        pool_size=settings.DATABASE_POOL_SIZE,
    )

    cleanup_task = asyncio.create_task(_otp_cleanup_loop())
    start_scheduler()
    start_notification_scheduler()

    yield

    shutdown_notification_scheduler()
    shutdown_scheduler()

    cleanup_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task

    await engine.dispose()
    logger.info("Engine disposed")
    logger.info("Application shutdown complete")
