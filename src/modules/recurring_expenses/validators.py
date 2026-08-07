"""Cross-field validation helpers for recurring-expense request schemas.

Field-level `description` validation is *not* redefined here — `schemas.py`
imports `expenses.validators.validate_description` directly, since a
recurring expense's description becomes a generated expense's description
verbatim and must satisfy the exact same rule.
"""

from datetime import date

from src.modules.recurring_expenses.exceptions import InvalidRecurringExpenseDateRangeError


def validate_date_range(start_date: date, end_date: date | None) -> None:
    if end_date is not None and end_date < start_date:
        raise InvalidRecurringExpenseDateRangeError()
