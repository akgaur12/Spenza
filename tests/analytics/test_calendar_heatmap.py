"""Integration tests for `GET /api/v1/analytics/calendar-heatmap`."""

from datetime import date, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from src.core.timezone import APP_TIMEZONE
from tests.analytics.helpers import (
    category_id_by_name,
    create_expense,
    get_calendar_heatmap,
    login_user_a,
    login_user_b,
    switch_to_user_a,
)
from tests.conftest import RecordingEmailBackend


def _now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


def _local(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=APP_TIMEZONE)


def _day(data: dict[str, Any], iso_date: str) -> dict[str, Any]:
    match: dict[str, Any] | None = next((d for d in data["data"] if d["date"] == iso_date), None)
    assert match is not None, f"no heatmap entry for {iso_date!r}"
    return match


# ── Auth ─────────────────────────────────────────────────────────────────


async def test_heatmap_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/analytics/calendar-heatmap")
    assert response.status_code == 401


async def test_heatmap_accessible_when_authenticated(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/analytics/calendar-heatmap")
    assert response.status_code == 200


# ── Year resolution ──────────────────────────────────────────────────────


async def test_current_year_default(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client)
    assert data["year"] == _now_local().year


async def test_explicit_year(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client, year=2026)
    assert data["year"] == 2026


async def test_invalid_year_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/analytics/calendar-heatmap", params={"year": 1500})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_YEAR"

    response_far_future = await client.get(
        "/api/v1/analytics/calendar-heatmap", params={"year": _now_local().year + 50}
    )
    assert response_far_future.status_code == 400
    assert response_far_future.json()["error_code"] == "INVALID_YEAR"


# ── Day coverage ─────────────────────────────────────────────────────────


async def test_normal_year_has_365_days(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client, year=2026)  # 2026 is not a leap year
    assert len(data["data"]) == 365


async def test_leap_year_has_366_days(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client, year=2024)  # 2024 is a leap year
    assert len(data["data"]) == 366
    feb_29 = _day(data, "2024-02-29")
    assert feb_29["month"] == 2
    assert feb_29["day"] == 29


async def test_january_first_and_december_31_included(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client, year=2026)
    jan1 = _day(data, "2026-01-01")
    assert jan1["month"] == 1
    assert jan1["day"] == 1
    dec31 = _day(data, "2026-12-31")
    assert dec31["month"] == 12
    assert dec31["day"] == 31


async def test_no_invalid_dates_generated(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client, year=2026)  # not a leap year
    dates = {d["date"] for d in data["data"]}
    assert "2026-02-30" not in dates
    assert "2026-02-29" not in dates
    assert "2026-04-31" not in dates
    # Every date parses back cleanly, with no duplicates.
    assert len(dates) == len(data["data"])
    for d in data["data"]:
        date.fromisoformat(d["date"])


async def test_no_expenses_returns_all_zero_value_days(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client, year=2026)
    assert data["total_spending"] == "0.00"
    assert data["expense_count"] == 0
    assert data["max_daily_spending"] == "0.00"
    assert len(data["data"]) == 365
    assert all(d["total"] == "0.00" and d["expense_count"] == 0 for d in data["data"])


# ── Totals, counts, max ────────────────────────────────────────────────────


async def test_daily_totals_counts_and_max_daily_spending(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2026, 1, 1)), amount="278.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2026, 1, 2)), amount="500.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2026, 1, 2)), amount="350.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2026, 1, 5)), amount="5200.00"
    )

    data = await get_calendar_heatmap(client, year=2026)

    jan1 = _day(data, "2026-01-01")
    assert jan1["total"] == "278.00"
    assert jan1["expense_count"] == 1

    jan2 = _day(data, "2026-01-02")
    assert jan2["total"] == "850.00"
    assert jan2["expense_count"] == 2

    jan3 = _day(data, "2026-01-03")
    assert jan3["total"] == "0.00"
    assert jan3["expense_count"] == 0

    assert data["total_spending"] == "6328.00"
    assert data["expense_count"] == 4
    assert data["max_daily_spending"] == "5200.00"


async def test_heatmap_user_isolation(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    day = _local(date(2026, 3, 15))

    await login_user_a(client, email_backend)
    food_a = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_a, spent_at=day, amount="50.00")

    await login_user_b(client, email_backend)
    food_b = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_b, spent_at=day, amount="9999.00")

    await switch_to_user_a(client)
    data = await get_calendar_heatmap(client, year=2026)
    assert _day(data, "2026-03-15")["total"] == "50.00"


# ── Year boundaries ──────────────────────────────────────────────────────


async def test_year_boundary_excludes_adjacent_years(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    year_start = _local(date(2026, 1, 1))
    just_before = year_start - timedelta(seconds=1)  # 2025-12-31
    year_end = _local(date(2026, 12, 31))
    just_after = year_end + timedelta(days=1)  # 2027-01-01

    await create_expense(client, category_id=food_id, spent_at=just_before, amount="111.00")
    await create_expense(client, category_id=food_id, spent_at=year_start, amount="222.00")
    await create_expense(client, category_id=food_id, spent_at=year_end, amount="333.00")
    await create_expense(client, category_id=food_id, spent_at=just_after, amount="444.00")

    data = await get_calendar_heatmap(client, year=2026)
    assert data["total_spending"] == "555.00"
    assert _day(data, "2026-01-01")["total"] == "222.00"
    assert _day(data, "2026-12-31")["total"] == "333.00"


# ── Future days ──────────────────────────────────────────────────────────


async def test_future_days_flagged_and_past_days_are_not(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    now_local = _now_local()
    current_year = now_local.year

    data = await get_calendar_heatmap(client, year=current_year)

    today_entry = _day(data, now_local.date().isoformat())
    assert today_entry["is_future"] is False

    first_day = _day(data, date(current_year, 1, 1).isoformat())
    assert first_day["is_future"] == (date(current_year, 1, 1) > now_local.date())

    for entry in data["data"]:
        expected_future = date.fromisoformat(entry["date"]) > now_local.date()
        assert entry["is_future"] == expected_future


async def test_past_year_has_no_future_days(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_calendar_heatmap(client, year=2020)
    assert all(d["is_future"] is False for d in data["data"])
