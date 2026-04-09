"""Add job_runs table

Revision ID: 009
Revises: 008
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_name", sa.String(100), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("pets_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_details", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.String(200), nullable=False, server_default="scheduler"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_job_runs_job_name"), "job_runs", ["job_name"])


def downgrade() -> None:
    op.drop_index(op.f("ix_job_runs_job_name"), table_name="job_runs")
    op.drop_table("job_runs")
