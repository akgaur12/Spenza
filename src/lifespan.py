"""Application startup/shutdown hooks."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from src.core.app_config import settings
from src.core.database import engine
from src.core.logger import get_logger

logger = get_logger(__name__)


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

    yield

    await engine.dispose()
    logger.info("Engine disposed")
    logger.info("Application shutdown complete")
