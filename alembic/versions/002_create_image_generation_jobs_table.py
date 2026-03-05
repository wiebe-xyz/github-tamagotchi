"""Create image_generation_jobs table

Revision ID: 002
Revises: 001
Create Date: 2026-01-14

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_generation_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pet_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Index for efficient queue queries (pending jobs by creation time)
    op.create_index(
        "ix_image_generation_jobs_status_created",
        "image_generation_jobs",
        ["status", "created_at"],
    )
    # Index for looking up jobs by pet
    op.create_index(
        "ix_image_generation_jobs_pet_id",
        "image_generation_jobs",
        ["pet_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_image_generation_jobs_pet_id", table_name="image_generation_jobs")
    op.drop_index(
        "ix_image_generation_jobs_status_created", table_name="image_generation_jobs"
    )
    op.drop_table("image_generation_jobs")
