"""Add pet achievements table

Revision ID: 014
Revises: 013
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pet_achievements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pet_id",
            sa.Integer(),
            sa.ForeignKey("pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("achievement_id", sa.String(50), nullable=False),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("pet_id", "achievement_id"),
    )
    op.create_index("ix_pet_achievements_pet_id", "pet_achievements", ["pet_id"])


def downgrade() -> None:
    op.drop_index("ix_pet_achievements_pet_id", table_name="pet_achievements")
    op.drop_table("pet_achievements")
