"""Async SQLAlchemy engine, session factory, and declarative base."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime, TypeDecorator

from src.core.app_config import settings
from src.core.exceptions import AppError


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models (used by Alembic autogenerate)."""


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware `DateTime` that is safe across dialects.

    asyncpg round-trips `tzinfo` natively, but SQLite (used by the test suite)
    silently drops it on read — comparing the naive result against
    `datetime.now(UTC)` then raises. This decorator normalizes both directions
    to UTC-aware, so model code never has to special-case the dialect.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class TimestampMixin:
    """Adds `created_at` / `updated_at` columns with UTC-aware timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


def create_engine(database_url: str | None = None, **engine_kwargs: object) -> AsyncEngine:
    """Build the async engine. Accepts an override URL/kwargs (used by the test suite)."""
    kwargs: dict[str, object] = {
        "echo": settings.DATABASE_ECHO,
        "pool_pre_ping": True,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
    }
    kwargs.update(engine_kwargs)
    return create_async_engine(database_url or settings.DATABASE_URL, **kwargs)


engine: AsyncEngine = create_engine()
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped `AsyncSession`.

    Unit-of-work semantics: commits once the request handler returns
    successfully. An `AppError` is an expected business outcome (wrong
    password, invalid OTP, ...) whose side effects — e.g. incrementing a
    failed-attempt counter — must still persist, so it also commits. Only
    an unexpected exception rolls back.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except AppError:
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
