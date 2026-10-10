"""Delete the stock FastMCP token rows from oauth_kv_store.

mcp/auth.py now issues and checks MCP tokens itself, in its own
collections. The old collections held one-year access tokens with no
refresh token and the GitHub tokens behind them in plain text. Nothing
reads them anymore, so they are deleted. Registered clients
(mcp-oauth-proxy-clients) are kept, so a client only has to log in again
once and does not have to re-register.

Revision ID: 035
Revises: 034
Create Date: 2026-10-10
"""

import sqlalchemy as sa

from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None

_LEGACY_COLLECTIONS = ("mcp-jti-mappings", "mcp-upstream-tokens", "mcp-refresh-tokens")


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM oauth_kv_store WHERE collection IN :collections").bindparams(
            sa.bindparam("collections", expanding=True)
        ),
        {"collections": list(_LEGACY_COLLECTIONS)},
    )


def downgrade() -> None:
    # Deleted tokens cannot be restored; clients log in again.
    pass
