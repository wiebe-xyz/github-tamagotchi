"""Add star_count and fork_count to pets table.

Revision ID: 025
Revises: 024
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pets", sa.Column("star_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "pets", sa.Column("fork_count", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("pets", "fork_count")
    op.drop_column("pets", "star_count")
