"""Add badge_style column to pets

Revision ID: 016
Revises: 015
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column(
            "badge_style",
            sa.String(20),
            nullable=False,
            server_default="playful",
        ),
    )


def downgrade() -> None:
    op.drop_column("pets", "badge_style")
