"""Add care-mechanic fields: mess/cleanup and boredom tracking.

Part of the classic Tamagotchi care mechanics (mess, boredom, hunger-from-
neglect, sleep cycle). Hunger-from-neglect reuses the existing
pets.last_fed_at column; the sleep cycle is computed from wall-clock time
and needs no persisted state.

Revision ID: 032
Revises: 031
Create Date: 2026-09-04
"""

import sqlalchemy as sa

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column("mess_level", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "pets",
        sa.Column("last_cleaned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "pets",
        sa.Column("last_played_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pets", "last_played_at")
    op.drop_column("pets", "last_cleaned_at")
    op.drop_column("pets", "mess_level")
