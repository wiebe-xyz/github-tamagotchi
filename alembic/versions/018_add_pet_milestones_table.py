"""Add pet milestones table

Revision ID: 018
Revises: 017
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pet_milestones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "pet_id",
            sa.Integer(),
            sa.ForeignKey("pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("old_stage", sa.String(20), nullable=False),
        sa.Column("new_stage", sa.String(20), nullable=False),
        sa.Column("experience", sa.Integer(), nullable=False),
        sa.Column("age_days", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_pet_milestones_pet_id", "pet_milestones", ["pet_id"])


def downgrade() -> None:
    op.drop_index("ix_pet_milestones_pet_id", table_name="pet_milestones")
    op.drop_table("pet_milestones")
