"""Calendar-period boundary helpers shared by reporting features (dashboard
summary, analytics) that bucket `Expense.spent_at` into calendar days,
weeks, months, and years in the app's single configured timezone
(`src.core.timezone.APP_TIMEZONE`).

Weeks run Monday -> Sunday everywhere in the app, for consistency across
features. These are plain, dependency-free functions so they can be unit
tested against synthetic "now" values without a database or the real wall
clock.
"""

from datetime import date, datetime, timedelta


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_week(dt: datetime) -> datetime:
    """Monday 00:00 of `dt`'s week."""
    start_of_today = start_of_day(dt)
    return start_of_today - timedelta(days=start_of_today.weekday())


def start_of_month(dt: datetime) -> datetime:
    return start_of_day(dt).replace(day=1)


def start_of_year(dt: datetime) -> datetime:
    return start_of_day(dt).replace(month=1, day=1)


def start_of_next_month(start_of_month_dt: datetime) -> datetime:
    if start_of_month_dt.month == 12:
        return start_of_month_dt.replace(year=start_of_month_dt.year + 1, month=1)
    return start_of_month_dt.replace(month=start_of_month_dt.month + 1)


def start_of_previous_month(start_of_month_dt: datetime) -> datetime:
    if start_of_month_dt.month == 1:
        return start_of_month_dt.replace(year=start_of_month_dt.year - 1, month=12)
    return start_of_month_dt.replace(month=start_of_month_dt.month - 1)


def end_of_month(dt: datetime) -> date:
    """The last calendar day (inclusive) of `dt`'s month."""
    return (start_of_next_month(start_of_month(dt)) - timedelta(days=1)).date()


def days_elapsed(start_of_period: datetime, now: datetime) -> int:
    """Days elapsed in an in-progress period, counting today as day 1."""
    return (now.date() - start_of_period.date()).days + 1


def months_elapsed_in_year(now: datetime) -> int:
    return now.month
