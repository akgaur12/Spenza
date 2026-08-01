"""Integration tests for `GET /api/v1/analytics/categories`."""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.periods import end_of_month, start_of_month
from src.core.timezone import APP_TIMEZONE
from src.modules.analytics.service import _percentage as service_percentage
from tests.analytics.helpers import (
    USER_B,
    USER_B_LOGIN,
    category_id_by_name,
    create_category,
    create_expense,
    get_category_analytics,
    login_user_a,
    login_user_b,
    switch_to_user_a,
)
from tests.conftest import RecordingEmailBackend, promote_to_admin

PERCENT = Decimal("0.01")


def _now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


def _percentage(part: Decimal, whole: Decimal) -> float:
    return float((part / whole * 100).quantize(PERCENT, rounding=ROUND_HALF_UP))


# ── Auth ─────────────────────────────────────────────────────────────────


async def test_category_analytics_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/analytics/categories")
    assert response.status_code == 401


async def test_category_analytics_accessible_when_authenticated(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/analytics/categories")
    assert response.status_code == 200


# ── Empty response ───────────────────────────────────────────────────────


async def test_no_expenses_returns_valid_empty_response(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    data = await get_category_analytics(client)

    assert data["total_spending"] == "0.00"
    assert data["expense_count"] == 0
    assert data["categories"] == []


# ── Privacy ──────────────────────────────────────────────────────────────


async def test_only_includes_current_users_expenses(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    now_local = _now_local()

    await login_user_a(client, email_backend)
    food_a = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_a, spent_at=now_local, amount="100.00")

    await login_user_b(client, email_backend)
    food_b = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_b, spent_at=now_local, amount="500.00")

    data_b = await get_category_analytics(client)
    assert data_b["total_spending"] == "500.00"

    await switch_to_user_a(client)
    data_a = await get_category_analytics(client)
    assert data_a["total_spending"] == "100.00"


async def test_admin_only_sees_own_expenses(
    client: AsyncClient,
    email_backend: RecordingEmailBackend,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now_local = _now_local()

    await login_user_a(client, email_backend)
    food_a = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_a, spent_at=now_local, amount="900.00")

    await login_user_b(client, email_backend)
    await promote_to_admin(db_session_factory, USER_B["email"])
    response = await client.post("/api/users/login", json=USER_B_LOGIN)
    assert response.status_code == 200, response.text

    data = await get_category_analytics(client)
    assert data["total_spending"] == "0.00"
    assert data["categories"] == []


# ── Totals, counts, percentages, averages, ordering ─────────────────────


async def test_category_totals_counts_percentages_and_ordering(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    transport_id = await category_id_by_name(client, "Transport")
    now_local = _now_local()

    # Food: 6500.00 across 2 expenses. Transport: 3200.00 across 1 expense.
    await create_expense(client, category_id=food_id, spent_at=now_local, amount="4500.00")
    await create_expense(client, category_id=food_id, spent_at=now_local, amount="2000.00")
    await create_expense(client, category_id=transport_id, spent_at=now_local, amount="3200.00")

    data = await get_category_analytics(client)
    assert data["total_spending"] == "9700.00"
    assert data["expense_count"] == 3

    categories = data["categories"]
    assert [c["name"] for c in categories] == ["Food", "Transport"]

    food = categories[0]
    assert food["total"] == "6500.00"
    assert food["expense_count"] == 2
    assert food["average_expense"] == "3250.00"
    assert food["percentage"] == _percentage(Decimal("6500.00"), Decimal("9700.00"))

    transport = categories[1]
    assert transport["total"] == "3200.00"
    assert transport["expense_count"] == 1
    assert transport["average_expense"] == "3200.00"
    assert transport["percentage"] == _percentage(Decimal("3200.00"), Decimal("9700.00"))


async def test_category_ordering_tie_break_is_deterministic(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    transport_id = await category_id_by_name(client, "Transport")
    now_local = _now_local()

    await create_expense(client, category_id=food_id, spent_at=now_local, amount="500.00")
    await create_expense(client, category_id=transport_id, spent_at=now_local, amount="500.00")

    data = await get_category_analytics(client)
    names = [c["name"] for c in data["categories"]]
    assert names == sorted(names)  # equal totals broken by name ascending


# ── System vs personal categories ────────────────────────────────────────


async def test_system_category_included(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")
    await create_expense(client, category_id=food_id, spent_at=_now_local(), amount="100.00")

    data = await get_category_analytics(client)
    assert any(c["name"] == "Food" for c in data["categories"])


async def test_personal_category_included(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    freelance_id = await create_category(client, "Freelance Tools")
    await create_expense(client, category_id=freelance_id, spent_at=_now_local(), amount="900.00")

    data = await get_category_analytics(client)
    freelance = next(c for c in data["categories"] if c["name"] == "Freelance Tools")
    assert freelance["total"] == "900.00"


async def test_inactive_historical_category_remains_represented(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    custom_id = await create_category(client, "Soon Inactive")
    await create_expense(client, category_id=custom_id, spent_at=_now_local(), amount="250.00")

    delete_response = await client.delete(f"/api/v1/categories/{custom_id}")
    assert delete_response.status_code == 204, delete_response.text

    data = await get_category_analytics(client)
    assert any(c["category_id"] == custom_id and c["total"] == "250.00" for c in data["categories"])


# ── Date range handling ───────────────────────────────────────────────────


async def test_custom_date_range_works(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    food_id = await category_id_by_name(client, "Food")

    await create_expense(
        client, category_id=food_id, spent_at=_now_local().replace(2026, 6, 15), amount="100.00"
    )
    await create_expense(
        client, category_id=food_id, spent_at=_now_local().replace(2026, 7, 15), amount="500.00"
    )

    data = await get_category_analytics(client, start_date="2026-06-01", end_date="2026-06-30")
    assert data["start_date"] == "2026-06-01"
    assert data["end_date"] == "2026-06-30"
    assert data["total_spending"] == "100.00"


async def test_default_range_is_full_current_calendar_month(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    now_local = _now_local()

    data = await get_category_analytics(client)
    assert data["start_date"] == start_of_month(now_local).date().isoformat()
    assert data["end_date"] == end_of_month(now_local).isoformat()


async def test_invalid_date_range_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get(
        "/api/v1/analytics/categories",
        params={"start_date": "2026-08-01", "end_date": "2026-07-01"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_DATE_RANGE"


async def test_partial_date_range_rejected(
    client: AsyncClient, email_backend: RecordingEmailBackend
) -> None:
    await login_user_a(client, email_backend)
    response = await client.get("/api/v1/analytics/categories", params={"start_date": "2026-07-01"})
    assert response.status_code == 400
    assert response.json()["error_code"] == "INCOMPLETE_DATE_RANGE"


# ── Pure helper unit test ─────────────────────────────────────────────────


def test_percentage_of_zero_whole_is_zero_not_a_division_error() -> None:
    # Structurally unreachable from the API (a non-empty category list always
    # implies a positive total_spending), but guarded defensively regardless.
    assert service_percentage(Decimal("0.00"), Decimal("0.00")) == 0.0
