"""Create pets table

Revision ID: 001
Revises:
Create Date: 2026-01-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo_owner", sa.String(length=255), nullable=False),
        sa.Column("repo_name", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False, server_default="egg"),
        sa.Column("mood", sa.String(length=20), nullable=False, server_default="content"),
        sa.Column("health", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("experience", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_fed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pets_repo", "pets", ["repo_owner", "repo_name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_pets_repo", table_name="pets")
    op.drop_table("pets")
