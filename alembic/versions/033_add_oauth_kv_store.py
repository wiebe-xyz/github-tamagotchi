"""Add oauth_kv_store table for durable MCP OAuth proxy state.

FastMCP's GitHubProvider (mcp/server.py's _build_auth()) previously had no
client_storage configured, so it fell back to an encrypted on-disk store
that doesn't survive a restart/redeploy and isn't shared across replicas —
every registered OAuth client (and in-flight transaction/code/refresh-token
state) was silently dropped whenever the pod restarted. See issue #262.

Revision ID: 033
Revises: 032
Create Date: 2026-09-05
"""

import sqlalchemy as sa

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_kv_store",
        sa.Column("collection", sa.String(255), primary_key=True),
        sa.Column("key", sa.String(512), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("oauth_kv_store")
