"""Drop mcp_tokens — replaced by interactive GitHub OAuth (DCR + PKCE) for
MCP auth, so there's no static token to store anymore. Introduced and
removed within the same day; never used outside this repo.

Revision ID: 031
Revises: 030
Create Date: 2026-09-03
"""

import sqlalchemy as sa

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_mcp_tokens_token_hash", table_name="mcp_tokens")
    op.drop_index("ix_mcp_tokens_user_id", table_name="mcp_tokens")
    op.drop_table("mcp_tokens")


def downgrade() -> None:
    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mcp_tokens_user_id", "mcp_tokens", ["user_id"])
    op.create_index("ix_mcp_tokens_token_hash", "mcp_tokens", ["token_hash"], unique=True)
