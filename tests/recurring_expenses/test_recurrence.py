"""Unit tests for `calculate_next_run_date` — no database, no HTTP: pure
date arithmetic per `Frequency`.
"""

from datetime import date

import pytest

from src.modules.recurring_expenses.enums import Frequency
from src.modules.recurring_expenses.recurrence import calculate_next_run_date


def test_daily_adds_one_day() -> None:
    assert calculate_next_run_date(date(2026, 8, 1), Frequency.DAILY) == date(2026, 8, 2)


def test_daily_rolls_over_month_end() -> None:
    assert calculate_next_run_date(date(2026, 8, 31), Frequency.DAILY) == date(2026, 9, 1)


def test_weekly_adds_seven_days() -> None:
    assert calculate_next_run_date(date(2026, 8, 1), Frequency.WEEKLY) == date(2026, 8, 8)


def test_monthly_same_day_next_month() -> None:
    assert calculate_next_run_date(date(2026, 8, 1), Frequency.MONTHLY) == date(2026, 9, 1)


def test_monthly_clamps_to_shorter_month_end() -> None:
    # 31 Jan + 1 month has no "31 Feb" -> clamp to Feb's actual last day.
    assert calculate_next_run_date(date(2026, 1, 31), Frequency.MONTHLY) == date(2026, 2, 28)


def test_monthly_clamps_to_leap_year_feb_29() -> None:
    assert calculate_next_run_date(date(2024, 1, 31), Frequency.MONTHLY) == date(2024, 2, 29)


def test_monthly_rolls_over_year_boundary() -> None:
    assert calculate_next_run_date(date(2026, 12, 15), Frequency.MONTHLY) == date(2027, 1, 15)


def test_quarterly_adds_three_months() -> None:
    assert calculate_next_run_date(date(2026, 1, 31), Frequency.QUARTERLY) == date(2026, 4, 30)


def test_quarterly_rolls_over_year_boundary() -> None:
    assert calculate_next_run_date(date(2026, 11, 30), Frequency.QUARTERLY) == date(2027, 2, 28)


def test_yearly_same_month_and_day_next_year() -> None:
    assert calculate_next_run_date(date(2026, 8, 15), Frequency.YEARLY) == date(2027, 8, 15)


def test_yearly_clamps_leap_day_to_non_leap_year() -> None:
    assert calculate_next_run_date(date(2024, 2, 29), Frequency.YEARLY) == date(2025, 2, 28)


@pytest.mark.parametrize(
    "frequency",
    [Frequency.DAILY, Frequency.WEEKLY, Frequency.MONTHLY, Frequency.QUARTERLY, Frequency.YEARLY],
)
def test_next_run_date_is_always_strictly_after_current(frequency: Frequency) -> None:
    current = date(2026, 3, 15)
    assert calculate_next_run_date(current, frequency) > current
