"""Seeds the default system categories into the per-test SQLite database.

The real seeding mechanism is the Alembic migration, which never runs
against the test suite's SQLite database (built straight from ORM metadata
via `Base.metadata.create_all`). This fixture reproduces that seed using
the same canonical `DEFAULT_SYSTEM_CATEGORIES` list so category tests see
the same defaults a real deployment would.
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
