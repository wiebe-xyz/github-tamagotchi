"""Add pet death fields

Revision ID: 012
Revises: 011
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column(
            "is_dead", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "pets",
        sa.Column("died_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pets",
        sa.Column("cause_of_death", sa.String(50), nullable=True),
    )
    op.add_column(
        "pets",
        sa.Column("grace_period_started", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pets", "grace_period_started")
    op.drop_column("pets", "cause_of_death")
    op.drop_column("pets", "died_at")
    op.drop_column("pets", "is_dead")
