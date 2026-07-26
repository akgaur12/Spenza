"""Seed the database with demo users for local development, or promote an
existing user to admin.

Usage:
  `make seed` (or `uv run python -m scripts.seed`)
    Creates a handful of already-verified accounts so you can log in
    immediately without running the OTP flow. Safe to re-run — existing
    emails are skipped.
  `make promote-admin EMAIL=someone@example.com`
    (or `uv run python -m scripts.seed --promote-admin someone@example.com`)
    Flips that user's role to admin. The user must already exist.
  `make demote-admin EMAIL=someone@example.com`
    (or `uv run python -m scripts.seed --demote-admin someone@example.com`)
    Flips that user's role back to a regular user. Refuses if they're the
    only admin left, to avoid locking everyone out of the admin API.
"""

import argparse
import asyncio

from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.core.security import hash_password
from src.modules.users.models import UserRole
from src.modules.users.repository import UserRepository

logger = get_logger(__name__)

DEMO_USERS = [
    {"email": "demo@spenza.dev", "username": "demo_user", "password": "DemoP@ssw0rd1"},
    {"email": "alice@spenza.dev", "username": "alice", "password": "DemoP@ssw0rd1"},
    {"email": "bob@spenza.dev", "username": "bob", "password": "DemoP@ssw0rd1"},
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        for demo in DEMO_USERS:
            existing = await users.get_by_email(demo["email"])
            if existing:
                logger.info("seed.skip_existing", email=demo["email"])
                continue

            user = users.create(
                email=demo["email"],
                username=demo["username"],
                password_hash=hash_password(demo["password"]),
            )
            user.is_verified = True
            await users.flush()
            logger.info("seed.created", email=demo["email"], username=demo["username"])

        await session.commit()

    print("Seed complete. Demo accounts (password: DemoP@ssw0rd1):")
    for demo in DEMO_USERS:
        print(f"  - {demo['email']} / {demo['username']}")


async def promote_admin(email: str) -> None:
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        user = await users.get_by_email(email)
        if user is None:
            print(f"No user found with email {email}")
            return

        user.role = UserRole.ADMIN
        await users.flush()
        await session.commit()
        logger.info("seed.promoted_admin", email=email)

    print(f"{email} is now an admin.")


async def demote_admin(email: str) -> None:
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        user = await users.get_by_email(email)
        if user is None:
            print(f"No user found with email {email}")
            return
        if user.role != UserRole.ADMIN:
            print(f"{email} is not an admin.")
            return

        if await users.count_by_role(UserRole.ADMIN) <= 1:
            print(f"Refusing to demote {email}: they're the only admin left.")
            return

        user.role = UserRole.USER
        await users.flush()
        await session.commit()
        logger.info("seed.demoted_admin", email=email)

    print(f"{email} is no longer an admin.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--promote-admin", metavar="EMAIL", help="Promote an existing user to the admin role"
    )
    parser.add_argument(
        "--demote-admin", metavar="EMAIL", help="Demote an existing admin back to a regular user"
    )
    args = parser.parse_args()

    if args.promote_admin:
        asyncio.run(promote_admin(args.promote_admin))
    elif args.demote_admin:
        asyncio.run(demote_admin(args.demote_admin))
    else:
        asyncio.run(seed())


if __name__ == "__main__":
    main()
