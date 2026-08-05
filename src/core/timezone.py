"""The single timezone used to compute calendar-period boundaries (today,
this week, this month, ...) for reporting features like the dashboard.

There is no per-user timezone preference yet, so every user's day/week/
month/year boundaries are computed in this one configured zone rather than
the database server's (or container's) local timezone.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.core.app_config import settings

APP_TIMEZONE = ZoneInfo(settings.APP_TIMEZONE)


def local_midnight_utc(d: date) -> datetime:
    """Anchor a plain calendar date to midnight in `APP_TIMEZONE`, then
    convert to UTC. This is the correct way to turn a `date` (e.g. a
    `start_date`/`end_date` filter, or an imported row's date) into a
    boundary comparable against `Expense.spent_at`, which is always stored
    in UTC — using raw UTC midnight instead would silently shift any
    expense from the first ~5-14 hours of the local day into the previous
    day's results, depending on `APP_TIMEZONE`'s offset.
    """
    return datetime(d.year, d.month, d.day, tzinfo=APP_TIMEZONE).astimezone(UTC)
