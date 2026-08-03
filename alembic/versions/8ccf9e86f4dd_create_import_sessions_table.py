"""create import_sessions table

Revision ID: 8ccf9e86f4dd
Revises: d9ed232fb44e
Create Date: 2026-07-31 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8ccf9e86f4dd"
down_revision: str | Sequence[str] | None = "d9ed232fb44e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "import_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CONFIRMED",
                name="importsessionstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_import_sessions_user_id"), "import_sessions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_import_sessions_user_id_status",
        "import_sessions",
        ["user_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_import_sessions_user_id_status", table_name="import_sessions")
    op.drop_index(op.f("ix_import_sessions_user_id"), table_name="import_sessions")
    op.drop_table("import_sessions")
