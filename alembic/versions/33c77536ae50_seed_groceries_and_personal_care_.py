"""seed groceries and personal care categories

Revision ID: 33c77536ae50
Revises: 90dc8a22d32c
Create Date: 2026-08-13 12:09:14.732104

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "33c77536ae50"
down_revision: str | Sequence[str] | None = "90dc8a22d32c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same namespace as c4abe0878b9f's seed, so IDs stay stable across migrations
# and re-running (e.g. downgrade then upgrade) is idempotent.
_SEED_NAMESPACE = uuid.UUID("2f3f3a4e-8b8a-4b1a-9a1a-6f6a1e2c9d10")
_NEW_CATEGORIES: list[tuple[str, str]] = [
    ("Groceries", "🛒"),
    ("Personal Care", "🧴"),
]


def _stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_SEED_NAMESPACE, name.lower())


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    insert_stmt = sa.text(
        "INSERT INTO categories (id, user_id, name, icon, is_active, created_at, updated_at) "
        "VALUES (:id, NULL, :name, :icon, true, now(), now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for name, icon in _NEW_CATEGORIES:
        conn.execute(insert_stmt, {"id": _stable_id(name), "name": name, "icon": icon})


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    delete_stmt = sa.text("DELETE FROM categories WHERE id = :id")
    for name, _ in _NEW_CATEGORIES:
        conn.execute(delete_stmt, {"id": _stable_id(name)})
