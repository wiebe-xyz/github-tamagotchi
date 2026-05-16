"""Add is_placeholder and claimed_at to pets for badge-driven auto-signup.

Revision ID: 029
Revises: 028
Create Date: 2026-05-16
"""

import sqlalchemy as sa

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column(
            "is_placeholder",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "pets",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_pets_is_placeholder", "pets", ["is_placeholder"]
    )


def downgrade() -> None:
    op.drop_index("ix_pets_is_placeholder", table_name="pets")
    op.drop_column("pets", "claimed_at")
    op.drop_column("pets", "is_placeholder")
