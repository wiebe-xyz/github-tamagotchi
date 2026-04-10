"""Add canonical_appearance column to pets table.

Revision ID: 026
Revises: 025
Create Date: 2026-04-10
"""

import sqlalchemy as sa

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column("canonical_appearance", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pets", "canonical_appearance")
