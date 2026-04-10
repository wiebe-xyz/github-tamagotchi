"""Add pet admin settings: contributor_badges_enabled, thresholds, excluded_contributors table

Revision ID: 022
Revises: 021
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new feature flag to pets
    op.add_column(
        "pets",
        sa.Column(
            "contributor_badges_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )

    # Add admin-configurable thresholds to pets
    op.add_column(
        "pets",
        sa.Column("hungry_after_days", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "pets",
        sa.Column("pr_review_sla_hours", sa.Integer(), nullable=False, server_default="48"),
    )
    op.add_column(
        "pets",
        sa.Column("issue_response_sla_days", sa.Integer(), nullable=False, server_default="7"),
    )

    # Create excluded_contributors table
    op.create_table(
        "excluded_contributors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pet_id", sa.Integer(), nullable=False),
        sa.Column("github_login", sa.String(255), nullable=False),
        sa.Column("excluded_by", sa.String(255), nullable=False),
        sa.Column(
            "excluded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["pet_id"], ["pets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pet_id", "github_login", name="ix_excluded_contributors_pet_login"),
    )
    op.create_index("ix_excluded_contributors_pet_id", "excluded_contributors", ["pet_id"])


def downgrade() -> None:
    op.drop_index("ix_excluded_contributors_pet_id", table_name="excluded_contributors")
    op.drop_table("excluded_contributors")
    op.drop_column("pets", "issue_response_sla_days")
    op.drop_column("pets", "pr_review_sla_hours")
    op.drop_column("pets", "hungry_after_days")
    op.drop_column("pets", "contributor_badges_enabled")
