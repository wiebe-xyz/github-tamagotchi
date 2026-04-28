"""Add push_subscriptions table for web push notifications.

Revision ID: 027
Revises: 026
Create Date: 2026-04-26
"""

import sqlalchemy as sa

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "pet_id",
            sa.Integer,
            sa.ForeignKey("pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("p256dh", sa.Text, nullable=False),
        sa.Column("auth", sa.Text, nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("pet_id", "endpoint", name="uq_push_sub_pet_endpoint"),
    )
    op.create_index("ix_push_subscriptions_pet_id", "push_subscriptions", ["pet_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_pet_id", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
