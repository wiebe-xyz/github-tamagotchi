"""Bearer-token authentication for the MCP server.

Personal API tokens, not GitHub OAuth — an MCP client can't drive a browser
OAuth redirect. A token is generated once from the dashboard, shown once,
and stored here only as a SHA-256 hash (irreversible, same approach as a
GitHub personal access token). Verifying a token resolves it to the owning
user; every MCP tool call is scoped to that user via AccessToken.claims.
"""

from __future__ import annotations

import hashlib
import secrets

from fastmcp.server.auth import AccessToken, TokenVerifier
from sqlalchemy import select

from github_tamagotchi.core.database import async_session_factory
from github_tamagotchi.models.mcp_token import McpToken
from github_tamagotchi.models.user import User

TOKEN_PREFIX = "tama_"


def generate_raw_token() -> str:
    """Generate a new raw bearer token. Only ever held by the caller, once."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """One-way hash of a raw token, for storage and lookup."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


class McpTokenVerifier(TokenVerifier):
    """Resolves a bearer token to the user who owns it."""

    async def verify_token(self, token: str) -> AccessToken | None:
        token_hash = hash_token(token)
        async with async_session_factory() as session:
            result = await session.execute(
                select(McpToken, User)
                .join(User, User.id == McpToken.user_id)
                .where(McpToken.token_hash == token_hash)
            )
            row = result.first()
            if row is None:
                return None
            mcp_token, user = row

            # Best-effort last-used stamp — never block or fail auth over it.
            try:
                from datetime import UTC, datetime

                mcp_token.last_used_at = datetime.now(UTC)
                await session.commit()
            except Exception:
                await session.rollback()

            return AccessToken(
                token=token,
                client_id=str(user.id),
                scopes=["pets:own"],
                claims={"user_id": user.id, "github_login": user.github_login},
            )
