"""create categories table and seed defaults

Revision ID: c4abe0878b9f
Revises: bac3f4618c51
Create Date: 2026-07-31 10:58:14.856561

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from src.modules.categories.seed_data import DEFAULT_SYSTEM_CATEGORIES

# revision identifiers, used by Alembic.
revision: str = "c4abe0878b9f"
down_revision: str | Sequence[str] | None = "bac3f4618c51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Stable per-name UUIDs so re-running the seed (e.g. after a downgrade then
# upgrade) is idempotent via `ON CONFLICT (id) DO NOTHING` instead of
# depending on random IDs matching up.
_SEED_NAMESPACE = uuid.UUID("2f3f3a4e-8b8a-4b1a-9a1a-6f6a1e2c9d10")


def _stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_SEED_NAMESPACE, name.lower())


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("icon", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_categories_user_id"), "categories", ["user_id"], unique=False)
    op.create_index(
        "ix_categories_user_id_is_active", "categories", ["user_id", "is_active"], unique=False
    )
    op.create_index(
        "ix_categories_name_lower", "categories", [sa.text("lower(name)")], unique=False
    )

    # Case-insensitive uniqueness, enforced at the database level:
    #   - one name per user among that user's own categories
    #   - one name overall among system categories (user_id IS NULL)
    # Two users may each have their own "Gym", but no user may have two
    # categories that differ only by case, and no two system categories may
    # either. Partial indexes require raw DDL (op.create_index has no
    # portable `where=` kwarg).
    op.execute(
        "CREATE UNIQUE INDEX ux_categories_system_name_lower "
        "ON categories (lower(name)) WHERE user_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_categories_user_name_lower "
        "ON categories (user_id, lower(name)) WHERE user_id IS NOT NULL"
    )

    conn = op.get_bind()
    insert_stmt = sa.text(
        "INSERT INTO categories (id, user_id, name, icon, is_active, created_at, updated_at) "
        "VALUES (:id, NULL, :name, :icon, true, now(), now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for name, icon in DEFAULT_SYSTEM_CATEGORIES:
        conn.execute(insert_stmt, {"id": _stable_id(name), "name": name, "icon": icon})


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ux_categories_user_name_lower")
    op.execute("DROP INDEX IF EXISTS ux_categories_system_name_lower")
    op.drop_index("ix_categories_name_lower", table_name="categories")
    op.drop_index("ix_categories_user_id_is_active", table_name="categories")
    op.drop_index(op.f("ix_categories_user_id"), table_name="categories")
    op.drop_table("categories")
