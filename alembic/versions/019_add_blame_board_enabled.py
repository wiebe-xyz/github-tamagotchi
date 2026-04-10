"""Add blame_board_enabled to pets

Revision ID: 019
Revises: 018
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column(
            "blame_board_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("pets", "blame_board_enabled")
