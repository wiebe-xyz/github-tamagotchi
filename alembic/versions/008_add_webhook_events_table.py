"""Add webhook_events table

Revision ID: 008
Revises: 007
Create Date: 2026-04-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repo_owner", sa.String(255), nullable=False),
        sa.Column("repo_name", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=True),
        sa.Column("payload_summary", sa.Text(), nullable=True),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_webhook_events_repo_owner"), "webhook_events", ["repo_owner"])
    op.create_index(op.f("ix_webhook_events_repo_name"), "webhook_events", ["repo_name"])
    op.create_index(op.f("ix_webhook_events_event_type"), "webhook_events", ["event_type"])


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_events_event_type"), table_name="webhook_events")
    op.drop_index(op.f("ix_webhook_events_repo_name"), table_name="webhook_events")
    op.drop_index(op.f("ix_webhook_events_repo_owner"), table_name="webhook_events")
    op.drop_table("webhook_events")
