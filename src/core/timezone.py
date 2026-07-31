"""The single timezone used to compute calendar-period boundaries (today,
this week, this month, ...) for reporting features like the dashboard.

There is no per-user timezone preference yet, so every user's day/week/
month/year boundaries are computed in this one configured zone rather than
the database server's (or container's) local timezone.
"""

from zoneinfo import ZoneInfo

from src.core.app_config import settings

APP_TIMEZONE = ZoneInfo(settings.APP_TIMEZONE)
