"""Canonical set of default system categories.

Single source of truth shared by the Alembic migration (which seeds
Postgres) and the test suite (which seeds the per-test SQLite database
directly, since tests build schema from ORM metadata and never run
migrations).
"""

DEFAULT_SYSTEM_CATEGORIES: list[tuple[str, str]] = [
    ("Food", "🍔"),
    ("Transport", "🚕"),
    ("Shopping", "🛍️"),
    ("Rent", "🏠"),
    ("Bills", "💡"),
    ("Entertainment", "🎬"),
    ("Health", "🏥"),
    ("Education", "📚"),
    ("Travel", "✈️"),
    ("Other", "📦"),
]
