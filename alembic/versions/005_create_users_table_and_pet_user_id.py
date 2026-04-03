"""Create users table and add user_id to pets

Revision ID: 005
Revises: 004
Create Date: 2026-04-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("github_id", sa.Integer(), nullable=False),
        sa.Column("github_login", sa.String(length=255), nullable=False),
        sa.Column("github_avatar_url", sa.String(length=500), nullable=True),
        sa.Column("encrypted_token", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_id"),
    )
    op.create_index("ix_users_github_id", "users", ["github_id"])

    op.add_column("pets", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_pets_user_id", "pets", ["user_id"])
    op.create_foreign_key("fk_pets_user_id", "pets", "users", ["user_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_pets_user_id", "pets", type_="foreignkey")
    op.drop_index("ix_pets_user_id", table_name="pets")
    op.drop_column("pets", "user_id")
    op.drop_index("ix_users_github_id", table_name="users")
    op.drop_table("users")
