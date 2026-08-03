"""Integration tests for `GET /api/v1/dashboard/summary`, plus focused unit
tests for the pure period-boundary helpers in `src.modules.dashboard.service`
(these don't depend on the real wall clock, so edge cases like the
January -> December rollover can be tested directly).
"""

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.periods import (
    days_elapsed,
    months_elapsed_in_year,
    start_of_day,
    start_of_month,
    start_of_previous_month,
    start_of_week,
    start_of_year,
)
from src.core.timezone import APP_TIMEZONE
from tests.conftest import RecordingEmailBackend, promote_to_admin, register_verified_user

USER_A = {"email": "user.a@example.com", "password": "SecureP@ss1"}
USER_A_SIGNUP = {**USER_A, "username": "user_a"}
USER_A_LOGIN = {"identifier": USER_A["email"], "password": USER_A["password"]}

USER_B = {"email": "user.b@example.com", "password": "SecureP@ss1"}
USER_B_SIGNUP = {**USER_B, "username": "user_b"}
USER_B_LOGIN = {"identifier": USER_B["email"], "password": USER_B["password"]}

CENTS = Decimal("0.01")
PERCENT = Decimal("0.01")


# ── Test helpers ─────────────────────────────────────────────────────────


async def _login_user_a(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_A_SIGNUP)
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def _login_user_b(client: AsyncClient, email_backend: RecordingEmailBackend) -> None:
    await register_verified_user(client, email_backend, USER_B_SIGNUP)
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text


async def _switch_to_user_a(client: AsyncClient) -> None:
    response = await client.post("/api/users/login", json=USER_A_LOGIN)
    assert response.status_code == 200, response.text


async def _category_id_by_name(client: AsyncClient, name: str) -> str:
    response = await client.get("/api/v1/categories")
    assert response.status_code == 200, response.text
    items = response.json()["data"]["items"]
    category_id: str = next(i for i in items if i["name"] == name)["id"]
    return category_id


async def _create_category(client: AsyncClient, name: str, icon: str | None = None) -> str:
    payload: dict[str, object] = {"name": name}
    if icon is not None:
        payload["icon"] = icon
    response = await client.post("/api/v1/categories", json=payload)
    assert response.status_code == 201, response.text
    category_id: str = response.json()["data"]["id"]
    return category_id


async def _create_expense(
    client: AsyncClient,
    *,
    category_id: str,
    spent_at: datetime,
    description: str = "Expense",
    amount: str = "100.00",
) -> dict[str, Any]:
    # Sent pre-converted to UTC: the test suite's SQLite database silently
    # drops any non-UTC offset on read instead of converting it (PostgreSQL
    # handles any offset correctly), so tests must submit `spent_at` values
    # that are already UTC to get deterministic boundary behavior.
    response = await client.post(
        "/api/v1/expenses",
        json={
            "category_id": category_id,
            "description": description,
            "amount": amount,
            "spent_at": spent_at.astimezone(UTC).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def _get_dashboard(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


def _now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


def _quantize(value: Decimal) -> str:
    return str(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def _divide(total: Decimal, denominator: int) -> str:
    return _quantize(total / denominator)


# ── Auth ─────────────────────────────────────────────────────────────────


async def test_dashboard_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/dashboard/summary")
    assert response.status_code == 401


async def test_dashboard_accessible_when_authenticated(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    response = await client.get("/api/v1/dashboard/summary")
    assert response.status_code == 200


# ── Empty dashboard ──────────────────────────────────────────────────────


async def test_empty_dashboard_returns_zero_values(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    data = await _get_dashboard(client)

    assert data["today"] == {"total": "0.00", "expense_count": 0}
    assert data["this_week"] == {
        "total": "0.00",
        "expense_count": 0,
        "daily_average": "0.00",
    }
    assert data["this_month"] == {
        "total": "0.00",
        "expense_count": 0,
        "daily_average": "0.00",
        "average_expense": "0.00",
    }
    assert data["this_year"] == {
        "total": "0.00",
        "expense_count": 0,
        "monthly_average": "0.00",
        "average_expense": "0.00",
    }
    assert data["previous_month"] == {"total": "0.00", "expense_count": 0}
    assert data["month_comparison"] == {
        "difference": "0.00",
        "percentage_change": 0.0,
        "trend": "same",
    }
    assert data["top_category"] is None
    assert data["largest_expense"] is None


# ── Privacy ──────────────────────────────────────────────────────────────


async def test_dashboard_only_includes_current_users_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    now_local = _now_local()

    await _login_user_a(client, email_backend)
    food_a = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_a, spent_at=now_local, amount="100.00")

    await _login_user_b(client, email_backend)
    food_b = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_b, spent_at=now_local, amount="500.00")

    data_b = await _get_dashboard(client)
    assert data_b["today"]["total"] == "500.00"
    assert data_b["today"]["expense_count"] == 1

    await _switch_to_user_a(client)
    data_a = await _get_dashboard(client)
    assert data_a["today"]["total"] == "100.00"
    assert data_a["today"]["expense_count"] == 1


async def test_admin_dashboard_only_shows_own_expenses(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now_local = _now_local()

    await _login_user_a(client, email_backend)
    food_a = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_a, spent_at=now_local, amount="900.00")

    await _login_user_b(client, email_backend)
    await promote_to_admin(db_session_factory, USER_B["email"])
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text

    data = await _get_dashboard(client)
    assert data["today"]["total"] == "0.00"
    assert data["today"]["expense_count"] == 0


# ── Today ────────────────────────────────────────────────────────────────


async def test_today_total_and_count(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    now_local = _now_local()
    today_start = start_of_day(now_local)

    await _create_expense(client, category_id=food_id, spent_at=today_start, amount="100.00")
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=today_start.replace(hour=12),
        amount="200.00",
    )
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=today_start.replace(hour=23, minute=59, second=59),
        amount="150.00",
    )

    data = await _get_dashboard(client)
    assert data["today"]["total"] == "450.00"
    assert data["today"]["expense_count"] == 3


async def test_yesterdays_expenses_excluded_from_today(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    yesterday_end = start_of_day(_now_local()) - timedelta(seconds=1)

    await _create_expense(client, category_id=food_id, spent_at=yesterday_end, amount="999.00")

    data = await _get_dashboard(client)
    assert data["today"]["total"] == "0.00"
    assert data["today"]["expense_count"] == 0


# ── Week ─────────────────────────────────────────────────────────────────


async def test_week_total_count_and_daily_average(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    now_local = _now_local()
    week_start = start_of_week(now_local)

    await _create_expense(client, category_id=food_id, spent_at=week_start, amount="1000.00")
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=week_start + timedelta(seconds=1),
        amount="2250.00",
    )

    data = await _get_dashboard(client)
    elapsed = days_elapsed(week_start, start_of_day(now_local))

    assert data["this_week"]["total"] == "3250.00"
    assert data["this_week"]["expense_count"] == 2
    assert data["this_week"]["daily_average"] == _divide(Decimal("3250.00"), elapsed)


async def test_previous_week_expenses_excluded(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    before_week = start_of_week(_now_local()) - timedelta(seconds=1)

    await _create_expense(client, category_id=food_id, spent_at=before_week, amount="500.00")

    data = await _get_dashboard(client)
    assert data["this_week"]["total"] == "0.00"
    assert data["this_week"]["expense_count"] == 0


async def test_week_boundary_is_monday(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    week_start = start_of_week(_now_local())

    # Monday 00:00:00 itself belongs to this week...
    await _create_expense(client, category_id=food_id, spent_at=week_start, amount="10.00")
    # ...but one second earlier (Sunday 23:59:59) belongs to last week.
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=week_start - timedelta(seconds=1),
        amount="20.00",
    )

    data = await _get_dashboard(client)
    assert data["this_week"]["total"] == "10.00"
    assert data["this_week"]["expense_count"] == 1


# ── Month ────────────────────────────────────────────────────────────────


async def test_month_total_count_daily_average_and_average_expense(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    now_local = _now_local()
    month_start = start_of_month(now_local)

    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="1000.00")
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=month_start + timedelta(seconds=1),
        amount="500.00",
    )

    data = await _get_dashboard(client)
    elapsed = days_elapsed(month_start, start_of_day(now_local))

    assert data["this_month"]["total"] == "1500.00"
    assert data["this_month"]["expense_count"] == 2
    assert data["this_month"]["daily_average"] == _divide(Decimal("1500.00"), elapsed)
    assert data["this_month"]["average_expense"] == _divide(Decimal("1500.00"), 2)


async def test_previous_months_expenses_excluded_from_this_month(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    before_month = start_of_month(_now_local()) - timedelta(seconds=1)

    await _create_expense(client, category_id=food_id, spent_at=before_month, amount="500.00")

    data = await _get_dashboard(client)
    assert data["this_month"]["total"] == "0.00"
    assert data["this_month"]["expense_count"] == 0
    assert data["this_month"]["average_expense"] == "0.00"


# ── Year ─────────────────────────────────────────────────────────────────


async def test_year_total_count_monthly_average_and_average_expense(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    now_local = _now_local()
    year_start = start_of_year(now_local)

    await _create_expense(client, category_id=food_id, spent_at=year_start, amount="3000.00")
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=year_start + timedelta(seconds=1),
        amount="1000.00",
    )

    data = await _get_dashboard(client)
    months_elapsed = months_elapsed_in_year(now_local)

    assert data["this_year"]["total"] == "4000.00"
    assert data["this_year"]["expense_count"] == 2
    assert data["this_year"]["monthly_average"] == _divide(Decimal("4000.00"), months_elapsed)
    assert data["this_year"]["average_expense"] == _divide(Decimal("4000.00"), 2)


async def test_previous_years_expenses_excluded_from_this_year(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    before_year = start_of_year(_now_local()) - timedelta(seconds=1)

    await _create_expense(client, category_id=food_id, spent_at=before_year, amount="500.00")

    data = await _get_dashboard(client)
    assert data["this_year"]["total"] == "0.00"
    assert data["this_year"]["expense_count"] == 0


# ── Previous month ───────────────────────────────────────────────────────


async def test_previous_month_total_and_count(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    month_start = start_of_month(_now_local())
    previous_month_start = start_of_previous_month(month_start)

    await _create_expense(
        client, category_id=food_id, spent_at=previous_month_start, amount="1620.00"
    )
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=previous_month_start + timedelta(seconds=1),
        amount="500.00",
    )
    # This month and two-months-back must not leak into "previous month".
    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="999.00")
    await _create_expense(
        client,
        category_id=food_id,
        spent_at=previous_month_start - timedelta(seconds=1),
        amount="999.00",
    )

    data = await _get_dashboard(client)
    assert data["previous_month"]["total"] == "2120.00"
    assert data["previous_month"]["expense_count"] == 2


def test_previous_month_handles_january_to_december_rollover() -> None:
    january = datetime(2027, 1, 15, 10, 0, 0, tzinfo=APP_TIMEZONE)
    month_start = start_of_month(january)

    previous_month_start = start_of_previous_month(month_start)

    assert previous_month_start == datetime(2026, 12, 1, tzinfo=APP_TIMEZONE)


def test_start_of_previous_month_normal_case() -> None:
    july = datetime(2026, 7, 20, tzinfo=APP_TIMEZONE)
    month_start = start_of_month(july)

    assert start_of_previous_month(month_start) == datetime(2026, 6, 1, tzinfo=APP_TIMEZONE)


# ── Month comparison ─────────────────────────────────────────────────────


async def test_month_comparison_spending_increased(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    month_start = start_of_month(_now_local())
    previous_month_start = start_of_previous_month(month_start)

    await _create_expense(
        client, category_id=food_id, spent_at=previous_month_start, amount="16200.00"
    )
    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="18450.00")

    data = await _get_dashboard(client)
    assert data["month_comparison"]["difference"] == "2250.00"
    assert data["month_comparison"]["percentage_change"] == 13.89
    assert data["month_comparison"]["trend"] == "up"


async def test_month_comparison_spending_decreased(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    month_start = start_of_month(_now_local())
    previous_month_start = start_of_previous_month(month_start)

    await _create_expense(
        client, category_id=food_id, spent_at=previous_month_start, amount="18450.00"
    )
    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="16200.00")

    data = await _get_dashboard(client)
    assert data["month_comparison"]["difference"] == "-2250.00"
    assert data["month_comparison"]["trend"] == "down"


async def test_month_comparison_spending_unchanged(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    month_start = start_of_month(_now_local())
    previous_month_start = start_of_previous_month(month_start)

    await _create_expense(
        client, category_id=food_id, spent_at=previous_month_start, amount="5000.00"
    )
    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="5000.00")

    data = await _get_dashboard(client)
    assert data["month_comparison"]["difference"] == "0.00"
    assert data["month_comparison"]["percentage_change"] == 0.0
    assert data["month_comparison"]["trend"] == "same"


async def test_month_comparison_both_zero(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)

    data = await _get_dashboard(client)
    assert data["month_comparison"] == {
        "difference": "0.00",
        "percentage_change": 0.0,
        "trend": "same",
    }


async def test_month_comparison_previous_zero_current_positive(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    month_start = start_of_month(_now_local())

    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="500.00")

    data = await _get_dashboard(client)
    assert data["previous_month"]["total"] == "0.00"
    assert data["month_comparison"]["difference"] == "500.00"
    assert data["month_comparison"]["percentage_change"] is None
    assert data["month_comparison"]["trend"] == "up"


# ── Top category ─────────────────────────────────────────────────────────


async def test_top_category_selected_with_correct_totals_and_percentage(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    transport_id = await _category_id_by_name(client, "Transport")
    month_start = start_of_month(_now_local())

    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="11950.00")
    await _create_expense(
        client,
        category_id=transport_id,
        spent_at=month_start + timedelta(seconds=1),
        amount="6500.00",
    )

    data = await _get_dashboard(client)
    assert data["this_month"]["total"] == "18450.00"
    top = data["top_category"]
    assert top is not None
    assert top["name"] == "Food"
    assert top["total"] == "11950.00"
    assert top["expense_count"] == 1
    expected_percentage = float(
        (Decimal("11950.00") / Decimal("18450.00") * 100).quantize(PERCENT, rounding=ROUND_HALF_UP)
    )
    assert top["percentage"] == expected_percentage


async def test_top_category_works_for_personal_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    freelance_id = await _create_category(client, "Freelance Tools")
    month_start = start_of_month(_now_local())

    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="100.00")
    await _create_expense(
        client,
        category_id=freelance_id,
        spent_at=month_start + timedelta(seconds=1),
        amount="900.00",
    )

    data = await _get_dashboard(client)
    top = data["top_category"]
    assert top is not None
    assert top["name"] == "Freelance Tools"
    assert top["category_id"] == freelance_id
    assert top["total"] == "900.00"


async def test_top_category_excludes_other_users_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    month_start = start_of_month(_now_local())

    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="50.00")

    await _login_user_b(client, email_backend)
    transport_id = await _category_id_by_name(client, "Transport")
    await _create_expense(client, category_id=transport_id, spent_at=month_start, amount="99999.00")

    await _switch_to_user_a(client)
    data = await _get_dashboard(client)
    top = data["top_category"]
    assert top is not None
    assert top["name"] == "Food"
    assert top["total"] == "50.00"


async def test_top_category_null_when_no_expenses_this_month(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    before_month = start_of_month(_now_local()) - timedelta(seconds=1)

    await _create_expense(client, category_id=food_id, spent_at=before_month, amount="500.00")

    data = await _get_dashboard(client)
    assert data["top_category"] is None


# ── Largest expense ──────────────────────────────────────────────────────


async def test_largest_expense_selected_with_category(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    month_start = start_of_month(_now_local())

    await _create_expense(
        client,
        category_id=food_id,
        description="Groceries",
        spent_at=month_start,
        amount="100.00",
    )
    await _create_expense(
        client,
        category_id=food_id,
        description="Rent",
        spent_at=month_start + timedelta(seconds=1),
        amount="15000.00",
    )

    data = await _get_dashboard(client)
    largest = data["largest_expense"]
    assert largest is not None
    assert largest["description"] == "Rent"
    assert largest["amount"] == "15000.00"
    assert largest["category"]["name"] == "Food"


async def test_largest_expense_excludes_other_users_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    month_start = start_of_month(_now_local())

    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    await _create_expense(client, category_id=food_id, spent_at=month_start, amount="50.00")

    await _login_user_b(client, email_backend)
    transport_id = await _category_id_by_name(client, "Transport")
    await _create_expense(client, category_id=transport_id, spent_at=month_start, amount="99999.00")

    await _switch_to_user_a(client)
    data = await _get_dashboard(client)
    largest = data["largest_expense"]
    assert largest is not None
    assert largest["amount"] == "50.00"


async def test_largest_expense_null_when_no_expenses_this_month(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    before_month = start_of_month(_now_local()) - timedelta(seconds=1)

    await _create_expense(client, category_id=food_id, spent_at=before_month, amount="500.00")

    data = await _get_dashboard(client)
    assert data["largest_expense"] is None


async def test_largest_expense_tie_is_deterministic(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    month_start = start_of_month(_now_local())

    first = await _create_expense(
        client,
        category_id=food_id,
        description="First",
        spent_at=month_start,
        amount="500.00",
    )
    second = await _create_expense(
        client,
        category_id=food_id,
        description="Second",
        spent_at=month_start,
        amount="500.00",
    )

    data_1 = await _get_dashboard(client)
    data_2 = await _get_dashboard(client)

    assert data_1["largest_expense"] is not None
    assert data_1["largest_expense"]["id"] in {first["id"], second["id"]}
    assert data_1["largest_expense"]["id"] == data_2["largest_expense"]["id"]


# ── Decimal precision ────────────────────────────────────────────────────


async def test_decimal_precision_avoids_floating_point_artifacts(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    now_local = _now_local()

    for amount in ("0.10", "0.20", "10.99", "999.99"):
        await _create_expense(client, category_id=food_id, spent_at=now_local, amount=amount)

    data = await _get_dashboard(client)
    assert data["today"]["total"] == "1011.28"
    assert data["today"]["expense_count"] == 4


# ── Timezone boundaries ──────────────────────────────────────────────────


async def test_expense_at_exact_local_midnight_counts_as_today(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    midnight = start_of_day(_now_local())

    await _create_expense(client, category_id=food_id, spent_at=midnight, amount="42.00")

    data = await _get_dashboard(client)
    assert data["today"]["total"] == "42.00"


async def test_expense_one_second_before_midnight_excluded_from_today(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await _login_user_a(client, email_backend)
    food_id = await _category_id_by_name(client, "Food")
    just_before_midnight = start_of_day(_now_local()) - timedelta(seconds=1)

    await _create_expense(
        client, category_id=food_id, spent_at=just_before_midnight, amount="42.00"
    )

    data = await _get_dashboard(client)
    assert data["today"]["total"] == "0.00"


# ── Pure boundary-helper unit tests ──────────────────────────────────────


def test_start_of_week_is_monday_for_any_weekday() -> None:
    for day in range(1, 8):  # 2026-06-01 was a Monday
        dt = datetime(2026, 6, day, 15, 30, tzinfo=APP_TIMEZONE)
        start = start_of_week(dt)
        assert start.weekday() == 0
        assert start.time().isoformat() == "00:00:00"
        assert start <= dt


def test_start_of_month_and_year() -> None:
    dt = datetime(2026, 7, 31, 23, 59, tzinfo=APP_TIMEZONE)
    assert start_of_month(dt) == datetime(2026, 7, 1, tzinfo=APP_TIMEZONE)
    assert start_of_year(dt) == datetime(2026, 1, 1, tzinfo=APP_TIMEZONE)


def test_days_elapsed_counts_today_as_day_one() -> None:
    start = datetime(2026, 7, 1, tzinfo=APP_TIMEZONE)
    same_day = datetime(2026, 7, 1, 18, 0, tzinfo=APP_TIMEZONE)
    ten_days_later = datetime(2026, 7, 10, 9, 0, tzinfo=APP_TIMEZONE)

    assert days_elapsed(start, same_day) == 1
    assert days_elapsed(start, ten_days_later) == 10


def test_months_elapsed_in_year_is_the_current_month_number() -> None:
    assert months_elapsed_in_year(datetime(2026, 7, 10, tzinfo=APP_TIMEZONE)) == 7
    assert months_elapsed_in_year(datetime(2026, 1, 1, tzinfo=APP_TIMEZONE)) == 1
    assert months_elapsed_in_year(datetime(2026, 12, 31, tzinfo=APP_TIMEZONE)) == 12
