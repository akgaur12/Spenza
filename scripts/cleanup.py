"""Run the unified daily housekeeping sweep on demand (CLI entrypoint).

Usage: `make cleanup` (or `uv run python -m scripts.cleanup`).

The app also runs this automatically once a day via an APScheduler job in
`src/modules/notifications/scheduler.py` (see `src.core.cleanup` for what it
purges), for as long as the process stays up. This script exists for
on-demand runs and for wiring into an *external* scheduler (cron, systemd
timer, or your hosting provider's scheduled-job feature) as a second line of
defense that doesn't depend on process uptime.
"""

import asyncio

from src.core.cleanup import run_cleanup_job


async def main() -> None:
    await run_cleanup_job()
    print("Cleanup job finished — see logs for per-table row counts.")


if __name__ == "__main__":
    asyncio.run(main())
