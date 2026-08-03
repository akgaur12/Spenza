"""Pure, DB-free field parsing for import rows: dates and amounts.

Category resolution (needs the DB) and description validation (reuses
`src.modules.expenses.validators.validate_description` directly) live in
`import_service.py`, which classifies failures from here into the row-level
`ImportRowErrorCode`s.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError

_MONTH_ABBR = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DATE_PATTERN = re.compile(r"^(\d{1,2})-([A-Za-z]{3})-(\d{4})$")

# Plain digits with an optional 1-2 digit decimal part, after currency
# symbol/comma/whitespace stripping — deliberately stricter than `Decimal()`
# would accept, so e.g. "1e5" or "278.005" are rejected rather than silently
# admitted (see `parse_import_amount`).
_AMOUNT_TEXT_PATTERN = re.compile(r"^\d+(?:\.\d{1,2})?$")

# Mirrors `ExpenseCreate.amount` (`gt=0, max_digits=12, decimal_places=2`)
# exactly, so an imported amount is held to the same bar as one entered
# through the regular create-expense endpoint.
AmountAdapter: TypeAdapter[Decimal] = TypeAdapter(
    Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
)


class ImportValueError(ValueError):
    """A raw cell value could not be parsed into a valid import field."""


def parse_import_date(raw: Any) -> date:
    """Accepts an Excel-native `datetime`/`date` cell value as-is, or a
    string in the `DD-MMM-YYYY` format (e.g. `01-Jan-2025`). Month
    abbreviations are matched against a fixed table rather than
    `strptime("%d-%b-%Y")`, since `%b` is locale-dependent and would silently
    stop parsing "Jan" on a server not configured for an English locale.
    """
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ImportValueError("Date is required")

    match = _DATE_PATTERN.match(raw.strip())
    if not match:
        raise ImportValueError(f"Invalid date: {raw!r}")
    day_str, month_str, year_str = match.groups()
    month = _MONTH_ABBR.get(month_str.lower())
    if month is None:
        raise ImportValueError(f"Invalid date: {raw!r}")
    try:
        return date(int(year_str), month, int(day_str))
    except ValueError as exc:
        raise ImportValueError(f"Invalid date: {raw!r}") from exc


def parse_import_amount(raw: Any) -> Decimal:
    """Format-level parsing only: strips a leading `₹` and thousands
    commas/whitespace and validates the numeric shape. Does *not* enforce
    positivity or `NUMERIC(12,2)` bounds — see `validate_import_amount` for
    that, kept separate so callers can report `AMOUNT_MUST_BE_POSITIVE`
    distinctly from a plain `INVALID_AMOUNT`.
    """
    if raw is None or isinstance(raw, bool):
        raise ImportValueError(f"Invalid amount: {raw!r}")

    if isinstance(raw, int | float):
        candidate = str(Decimal(str(raw)))
    else:
        text = str(raw).strip()
        if not text:
            raise ImportValueError("Amount is required")
        candidate = text.replace("₹", "").replace(",", "").strip()
        if not _AMOUNT_TEXT_PATTERN.fullmatch(candidate):
            raise ImportValueError(f"Invalid amount: {raw!r}")

    try:
        return Decimal(candidate)
    except ArithmeticError as exc:
        raise ImportValueError(f"Invalid amount: {raw!r}") from exc


def validate_import_amount(value: Decimal) -> Decimal:
    """Enforce the same constraints as `ExpenseCreate.amount`. Raises
    `ImportValueError` for anything `parse_import_amount` let through that
    still doesn't fit `NUMERIC(12,2)` (e.g. too many integer digits).
    Positivity is checked by the caller first so it can be tagged
    `AMOUNT_MUST_BE_POSITIVE` instead of a generic `INVALID_AMOUNT`.
    """
    try:
        return AmountAdapter.validate_python(value)
    except ValidationError as exc:
        raise ImportValueError(str(exc)) from exc
