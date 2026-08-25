"""Regression tests for `LenientDate`: some local/smaller models emit
tool-call dates without zero-padding (e.g. "2026-7-1"), which pydantic's
strict ISO-8601 date parser otherwise rejects outright as "too short" —
seen in practice causing repeated tool-call failures/retries against a
real Ollama model. `LenientDate` normalizes the string before validation;
this guards that behavior for both optional (`DateRangeArgs`-derived) and
required (`ComparePeriodsArgs`-derived) date fields.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from src.modules.ai_assistant.tools.schemas import ComparePeriodsArgs, GetExpensesArgs


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-7-1", date(2026, 7, 1)),
        ("2026-07-01", date(2026, 7, 1)),
        ("2026-7-31", date(2026, 7, 31)),
        ("2026-12-9", date(2026, 12, 9)),
    ],
)
def test_optional_date_field_accepts_non_zero_padded_dates(raw: str, expected: date) -> None:
    args = GetExpensesArgs(start_date=raw, end_date=None)
    assert args.start_date == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-7-1", date(2026, 7, 1)),
        ("2026-07-01", date(2026, 7, 1)),
    ],
)
def test_required_date_field_accepts_non_zero_padded_dates(raw: str, expected: date) -> None:
    args = ComparePeriodsArgs(start_date=raw, end_date="2026-7-31")
    assert args.start_date == expected


def test_genuinely_invalid_date_still_raises() -> None:
    with pytest.raises(ValidationError):
        GetExpensesArgs(start_date="not-a-date", end_date=None)
