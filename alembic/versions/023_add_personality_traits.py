"""Add personality traits to pets table

Revision ID: 023
Revises: 022
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pets", sa.Column("personality_activity", sa.Float(), nullable=True))
    op.add_column("pets", sa.Column("personality_sociability", sa.Float(), nullable=True))
    op.add_column("pets", sa.Column("personality_bravery", sa.Float(), nullable=True))
    op.add_column("pets", sa.Column("personality_tidiness", sa.Float(), nullable=True))
    op.add_column("pets", sa.Column("personality_appetite", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("pets", "personality_appetite")
    op.drop_column("pets", "personality_tidiness")
    op.drop_column("pets", "personality_bravery")
    op.drop_column("pets", "personality_sociability")
    op.drop_column("pets", "personality_activity")
