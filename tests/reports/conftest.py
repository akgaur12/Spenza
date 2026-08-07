"""Seeds the default system categories for reports tests.

Mirrors `tests/analytics/conftest.py` / `tests/dashboard/conftest.py` —
expenses always reference a category, and the real seeding mechanism (the
Alembic migration) never runs against the test suite's SQLite database.
"""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.categories.models import Category
from src.modules.categories.seed_data import DEFAULT_SYSTEM_CATEGORIES


@pytest_asyncio.fixture(autouse=True)
async def _seed_system_categories(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        for name, icon in DEFAULT_SYSTEM_CATEGORIES:
            session.add(Category(user_id=None, name=name, icon=icon))
        await session.commit()
