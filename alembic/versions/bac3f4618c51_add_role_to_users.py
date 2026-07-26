"""add role to users

Revision ID: bac3f4618c51
Revises: ca32faabcf22
Create Date: 2026-07-26 13:31:18.883866

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bac3f4618c51"
down_revision: str | Sequence[str] | None = "ca32faabcf22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum("USER", "ADMIN", name="userrole", native_enum=False, length=20),
            nullable=False,
            server_default="USER",
        ),
    )
    op.alter_column("users", "role", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "role")
