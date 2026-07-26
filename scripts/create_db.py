"""Create the target Postgres database (parsed from `DATABASE_URL`) if it
doesn't already exist.

Usage: `make create-db` (or `uv run python -m scripts.create_db`).

Connects to the server's `postgres` maintenance database using the same
host/port/credentials as `DATABASE_URL`, then issues `CREATE DATABASE`
outside a transaction (required by Postgres). Safe to re-run — a no-op if
the database already exists.
"""

import asyncio
import re
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from src.core.app_config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

_VALID_DB_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _target_db_name(database_url: str) -> str:
    db_name = urlsplit(database_url).path.lstrip("/")
    if not _VALID_DB_NAME_RE.match(db_name):
        raise ValueError(f"Refusing to create database with unexpected name: {db_name!r}")
    return db_name


def _asyncpg_dsn(database_url: str, *, db_name: str) -> str:
    # SQLAlchemy URLs use the "postgresql+asyncpg://" scheme; asyncpg wants "postgresql://".
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    parts = urlsplit(dsn)
    return urlunsplit((parts.scheme, parts.netloc, f"/{db_name}", parts.query, parts.fragment))


async def create_db() -> None:
    target_db = _target_db_name(settings.DATABASE_URL)
    admin_dsn = _asyncpg_dsn(settings.DATABASE_URL, db_name="postgres")

    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", target_db)
        if exists:
            logger.info("create_db.already_exists", database=target_db)
            print(f"Database '{target_db}' already exists — nothing to do.")
            return

        await conn.execute(f'CREATE DATABASE "{target_db}"')
        logger.info("create_db.created", database=target_db)
        print(f"Database '{target_db}' created.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(create_db())
