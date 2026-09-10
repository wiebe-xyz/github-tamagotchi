"""Add last_poll_error to pets.

Records why the most recent poll couldn't read the repo (e.g. the shared
bot account lacks access to a private repo), so a pet that's simply
unreachable no longer decays like a genuinely neglected one. See issue #185
and specs/github-app-webhooks.md.

Revision ID: 034
Revises: 033
Create Date: 2026-09-10
"""

import sqlalchemy as sa

from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pets",
        sa.Column("last_poll_error", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pets", "last_poll_error")
