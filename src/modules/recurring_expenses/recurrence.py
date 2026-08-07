"""The one place recurrence-date arithmetic lives — `RecurringExpenseService`
calls `calculate_next_run_date` to advance a definition after each run;
nothing else in this module (or the scheduler) computes a date offset
itself, so the rule for "what's next" is defined exactly once.
"""

from calendar import monthrange
from datetime import date, timedelta

from src.modules.recurring_expenses.enums import Frequency


def _add_months(current: date, months: int) -> date:
    """`current` shifted forward by `months` calendar months, clamping the
    day-of-month to the target month's last day when it doesn't exist there
    (e.g. 31 Jan + 1 month -> 28/29 Feb) — never a `ValueError`, never a
    silent rollover into the following month.
    """
    total_month_index = current.month - 1 + months
    year = current.year + total_month_index // 12
    month = total_month_index % 12 + 1
    day = min(current.day, monthrange(year, month)[1])
    return date(year, month, day)


def calculate_next_run_date(current_date: date, frequency: Frequency) -> date:
    """The next occurrence date, exactly one period of `frequency` after
    `current_date`. Called with a recurring expense's own `next_run_date`
    (not "today") when advancing it after a run, so a late-running
    scheduler never compresses the schedule.
    """
    if frequency is Frequency.DAILY:
        return current_date + timedelta(days=1)
    if frequency is Frequency.WEEKLY:
        return current_date + timedelta(weeks=1)
    if frequency is Frequency.MONTHLY:
        return _add_months(current_date, 1)
    if frequency is Frequency.QUARTERLY:
        return _add_months(current_date, 3)
    return _add_months(current_date, 12)  # YEARLY
