"""Integration tests for `GET /api/v1/analytics/trends`."""

from datetime import date, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from src.core.periods import start_of_month, start_of_year
from src.core.timezone import APP_TIMEZONE
from tests.analytics.helpers import (
    category_id_by_name,
    create_expense,
    get_trend_analytics,
    login_user_a,
    login_user_b,
    switch_to_user_a,
)
from tests.conftest import RecordingEmailBackend


def _now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


def _local(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=APP_TIMEZONE)


def _point(data: dict[str, Any], period: str) -> dict[str, Any]:
    match: dict[str, Any] | None = next((p for p in data["data"] if p["period"] == period), None)
    periods = [p["period"] for p in data["data"]]
    assert match is not None, f"no data point for period {period!r} in {periods}"
    return match


# ── Auth ─────────────────────────────────────────────────────────────────


async def test_trend_analytics_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/analytics/trends")
    assert response.status_code == 401


async def test_trend_analytics_accessible_when_authenticated(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/analytics/trends")
    assert response.status_code == 200


async def test_default_interval_is_monthly(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_trend_analytics(client)
    assert data["interval"] == "monthly"


async def test_unsupported_interval_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/analytics/trends", params={"interval": "hourly"})
    assert response.status_code == 422


async def test_no_expenses_handled_correctly(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_trend_analytics(
        client,
        interval="daily",
        start_date="2026-07-01",
        end_date="2026-07-03",
    )
    assert data["total_spending"] == "0.00"
    assert data["expense_count"] == 0
    assert len(data["data"]) == 3
    assert all(p["total"] == "0.00" and p["expense_count"] == 0 for p in data["data"])


# ── Daily ────────────────────────────────────────────────────────────────


async def test_daily_trend_totals_counts_averages_and_gap_filling(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    day1 = _local(date(2026, 7, 1))
    day3 = _local(date(2026, 7, 3))
    await create_expense(client, category_id=food_id, spent_at=day1, amount="300.00")
    await create_expense(client, category_id=food_id, spent_at=day1, amount="200.00")
    await create_expense(client, category_id=food_id, spent_at=day3, amount="750.00")

    data = await get_trend_analytics(
        client, interval="daily", start_date="2026-07-01", end_date="2026-07-03"
    )
    assert len(data["data"]) == 3

    point1 = _point(data, "2026-07-01")
    assert point1["total"] == "500.00"
    assert point1["expense_count"] == 2
    assert point1["average_expense"] == "250.00"
    assert point1["start_date"] is None
    assert point1["end_date"] is None

    point2 = _point(data, "2026-07-02")
    assert point2["total"] == "0.00"
    assert point2["expense_count"] == 0
    assert point2["average_expense"] == "0.00"

    point3 = _point(data, "2026-07-03")
    assert point3["total"] == "750.00"
    assert point3["expense_count"] == 1


async def test_daily_trend_user_isolation(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    day = _local(date(2026, 7, 1))

    await login_user_a(client, email_backend)
    food_a = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_a, spent_at=day, amount="50.00")

    await login_user_b(client, email_backend)
    food_b = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_b, spent_at=day, amount="9999.00")

    await switch_to_user_a(client)
    data = await get_trend_analytics(
        client, interval="daily", start_date="2026-07-01", end_date="2026-07-01"
    )
    assert data["data"][0]["total"] == "50.00"


async def test_daily_trend_includes_leap_day(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    leap_day = _local(date(2028, 2, 29))
    await create_expense(client, category_id=food_id, spent_at=leap_day, amount="29.00")

    data = await get_trend_analytics(
        client, interval="daily", start_date="2028-02-28", end_date="2028-03-01"
    )
    assert len(data["data"]) == 3
    assert _point(data, "2028-02-29")["total"] == "29.00"


async def test_daily_default_range_is_current_month_so_far(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    now_local = _now_local()

    data = await get_trend_analytics(client, interval="daily")
    assert data["start_date"] == start_of_month(now_local).date().isoformat()
    assert data["end_date"] == now_local.date().isoformat()


# ── Weekly ───────────────────────────────────────────────────────────────


async def test_weekly_trend_monday_to_sunday_boundary(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    monday = _local(date(2026, 7, 20))
    sunday = _local(date(2026, 7, 26))
    previous_sunday = monday - timedelta(seconds=1)  # 2026-07-19, last week

    await create_expense(client, category_id=food_id, spent_at=monday, amount="1000.00")
    await create_expense(client, category_id=food_id, spent_at=sunday, amount="250.00")
    await create_expense(client, category_id=food_id, spent_at=previous_sunday, amount="999.00")

    data = await get_trend_analytics(
        client, interval="weekly", start_date="2026-07-20", end_date="2026-07-26"
    )
    assert len(data["data"]) == 1
    point = data["data"][0]
    assert point["period"] == "2026-W30"
    assert point["start_date"] == "2026-07-20"
    assert point["end_date"] == "2026-07-26"
    assert point["total"] == "1250.00"
    assert point["expense_count"] == 2


async def test_weekly_trend_handles_year_transition(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    # 2025-12-29 is a Monday that belongs to ISO week 2026-W01.
    monday = _local(date(2025, 12, 29))
    await create_expense(client, category_id=food_id, spent_at=monday, amount="777.00")

    data = await get_trend_analytics(
        client, interval="weekly", start_date="2025-12-29", end_date="2026-01-04"
    )
    assert len(data["data"]) == 1
    point = data["data"][0]
    assert point["period"] == "2026-W01"
    assert point["start_date"] == "2025-12-29"
    assert point["end_date"] == "2026-01-04"
    assert point["total"] == "777.00"


async def test_weekly_trend_gap_filling(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    week1_monday = _local(date(2026, 7, 6))
    week3_monday = _local(date(2026, 7, 20))
    await create_expense(client, category_id=food_id, spent_at=week1_monday, amount="100.00")
    await create_expense(client, category_id=food_id, spent_at=week3_monday, amount="300.00")

    data = await get_trend_analytics(
        client, interval="weekly", start_date="2026-07-06", end_date="2026-07-26"
    )
    assert len(data["data"]) == 3
    assert _point(data, "2026-W28")["total"] == "100.00"
    assert _point(data, "2026-W29")["total"] == "0.00"
    assert _point(data, "2026-W30")["total"] == "300.00"


async def test_weekly_and_monthly_default_range_is_current_year_so_far(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    now_local = _now_local()

    weekly_data = await get_trend_analytics(client, interval="weekly")
    assert weekly_data["start_date"] == start_of_year(now_local).date().isoformat()
    assert weekly_data["end_date"] == now_local.date().isoformat()

    monthly_data = await get_trend_analytics(client, interval="monthly")
    assert monthly_data["start_date"] == start_of_year(now_local).date().isoformat()
    assert monthly_data["end_date"] == now_local.date().isoformat()


# ── Monthly ──────────────────────────────────────────────────────────────


async def test_monthly_trend_totals_and_gap_filling(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2026, 1, 5)), amount="18200.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2026, 3, 10)), amount="16450.00"
    )

    data = await get_trend_analytics(
        client, interval="monthly", start_date="2026-01-01", end_date="2026-03-31"
    )
    assert len(data["data"]) == 3
    assert _point(data, "2026-01")["total"] == "18200.00"
    assert _point(data, "2026-02")["total"] == "0.00"
    assert _point(data, "2026-03")["total"] == "16450.00"


async def test_monthly_trend_month_boundary(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    month_start = start_of_month(_local(date(2026, 7, 15)))
    just_before = month_start - timedelta(seconds=1)
    await create_expense(client, category_id=food_id, spent_at=month_start, amount="100.00")
    await create_expense(client, category_id=food_id, spent_at=just_before, amount="999.00")

    data = await get_trend_analytics(
        client, interval="monthly", start_date="2026-07-01", end_date="2026-07-31"
    )
    assert len(data["data"]) == 1
    assert data["data"][0]["total"] == "100.00"


# ── Yearly ───────────────────────────────────────────────────────────────


async def test_yearly_trend_totals_and_gap_filling(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2024, 6, 1)), amount="10000.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=_local(date(2026, 6, 1)), amount="20000.00"
    )

    data = await get_trend_analytics(
        client, interval="yearly", start_date="2024-01-01", end_date="2026-12-31"
    )
    assert len(data["data"]) == 3
    assert _point(data, "2024")["total"] == "10000.00"
    assert _point(data, "2025")["total"] == "0.00"
    assert _point(data, "2026")["total"] == "20000.00"


async def test_yearly_trend_year_boundary(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    year_start = start_of_year(_local(date(2026, 6, 1)))
    just_before = year_start - timedelta(seconds=1)
    await create_expense(client, category_id=food_id, spent_at=year_start, amount="100.00")
    await create_expense(client, category_id=food_id, spent_at=just_before, amount="999.00")

    data = await get_trend_analytics(
        client, interval="yearly", start_date="2026-01-01", end_date="2026-12-31"
    )
    assert len(data["data"]) == 1
    assert data["data"][0]["total"] == "100.00"


async def test_yearly_default_range_is_last_five_years_through_today(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    now_local = _now_local()

    data = await get_trend_analytics(client, interval="yearly")
    assert data["start_date"] == date(now_local.year - 4, 1, 1).isoformat()
    assert data["end_date"] == now_local.date().isoformat()


# ── Date range validation ─────────────────────────────────────────────────


async def test_partial_date_range_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/analytics/trends", params={"start_date": "2026-07-01"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INCOMPLETE_DATE_RANGE"


async def test_invalid_date_range_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get(
        "/api/v1/analytics/trends",
        params={"start_date": "2026-08-01", "end_date": "2026-07-01"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_DATE_RANGE"


async def test_date_range_too_large_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get(
        "/api/v1/analytics/trends",
        params={"interval": "daily", "start_date": "1990-01-01", "end_date": "2026-12-31"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "DATE_RANGE_TOO_LARGE"
