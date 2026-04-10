"""Add contributor_relationships table

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
    op.create_table(
        "contributor_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pet_id", sa.Integer(), nullable=False),
        sa.Column("github_username", sa.String(255), nullable=False),
        sa.Column("standing", sa.String(20), nullable=False, server_default="neutral"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sins", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("good_deeds", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pet_id", "github_username"),
    )
    op.create_index("ix_contributor_relationships_pet_id", "contributor_relationships", ["pet_id"])


def downgrade() -> None:
    op.drop_index("ix_contributor_relationships_pet_id", table_name="contributor_relationships")
    op.drop_table("contributor_relationships")
