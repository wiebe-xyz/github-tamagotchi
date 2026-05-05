"""Add graveyard fields to pets and grave_flower_ips table.

Revision ID: 028
Revises: 027
Create Date: 2026-05-05
"""

import sqlalchemy as sa

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pets", sa.Column("eulogy", sa.String(280), nullable=True))
    op.add_column(
        "pets",
        sa.Column("flower_count", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "grave_flower_ips",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "pet_id",
            sa.Integer,
            sa.ForeignKey("pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column(
            "last_flower_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("pet_id", "ip_hash", name="uq_grave_flower_ip"),
    )
    op.create_index(
        "ix_grave_flower_ips_pet_id", "grave_flower_ips", ["pet_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_grave_flower_ips_pet_id", table_name="grave_flower_ips")
    op.drop_table("grave_flower_ips")
    op.drop_column("pets", "flower_count")
    op.drop_column("pets", "eulogy")
