"""Add skin fields to pets table

Revision ID: 020
Revises: 019
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column("skin", sa.String(length=20), nullable=False, server_default="classic"),
    )
    op.add_column(
        "pets",
        sa.Column("low_health_recoveries", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("pets", "low_health_recoveries")
    op.drop_column("pets", "skin")
