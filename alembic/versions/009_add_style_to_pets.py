"""Add style column to pets table

Revision ID: 009
Revises: 008
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column(
            "style",
            sa.String(30),
            nullable=False,
            server_default="kawaii",
        ),
    )


def downgrade() -> None:
    op.drop_column("pets", "style")
