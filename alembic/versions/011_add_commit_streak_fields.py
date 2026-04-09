"""Add commit streak fields to pets table

Revision ID: 011
Revises: 010
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column("commit_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pets",
        sa.Column("longest_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pets",
        sa.Column("last_streak_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pets", "last_streak_date")
    op.drop_column("pets", "longest_streak")
    op.drop_column("pets", "commit_streak")
