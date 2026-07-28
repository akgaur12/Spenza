"""Delete stale rows from `email_otps` (CLI entrypoint).

Usage: `make cleanup-otps` (or `uv run python -m scripts.cleanup_otps`).

The app also runs this automatically once a week via a background task in
`src/lifespan.py`, for as long as the process stays up — but that timer is
just an `asyncio.sleep`, so it resets on every restart and may rarely fire
in practice if the process gets redeployed often. This script exists for
on-demand runs and for wiring into an *external* scheduler (cron, systemd
timer, or your hosting provider's scheduled-job feature) as a second line of
defense that doesn't depend on process uptime.
"""

import asyncio

from src.core.database import AsyncSessionLocal
from src.core.logger import get_logger
from src.modules.users.service import cleanup_expired_otps

logger = get_logger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        deleted = await cleanup_expired_otps(session)
    logger.info("otp_cleanup.completed", deleted=deleted)
    print(f"Deleted {deleted} stale OTP row(s).")


if __name__ == "__main__":
    asyncio.run(main())
