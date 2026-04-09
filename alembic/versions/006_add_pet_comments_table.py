"""Add pet_comments table

Revision ID: 006
Revises: 005
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pet_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repo_owner", sa.String(length=255), nullable=False),
        sa.Column("repo_name", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("author_name", sa.String(length=100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pet_comments_repo_owner", "pet_comments", ["repo_owner"])
    op.create_index("ix_pet_comments_repo_name", "pet_comments", ["repo_name"])


def downgrade() -> None:
    op.drop_index("ix_pet_comments_repo_name", table_name="pet_comments")
    op.drop_index("ix_pet_comments_repo_owner", table_name="pet_comments")
    op.drop_table("pet_comments")
