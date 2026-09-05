"""OAuthKVStore model: durable backing for FastMCP's OAuth proxy state.

FastMCP's GitHubProvider (a subclass of OAuthProxy — see mcp/server.py's
_build_auth()) needs somewhere to persist OAuth state: registered Dynamic
Client Registration clients, in-flight authorization transactions,
one-time authorization codes, and refresh-token metadata. Left
unconfigured, OAuthProxy falls back to an encrypted on-disk store rooted in
the process's own local filesystem — wiped on every restart/redeploy and
not shared across replicas, which is exactly what broke every previously
registered MCP client in issue #262. This table gives that same small
key-value contract (see services/oauth_kv_store.py) a durable home in the
database everything else already lives in.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from github_tamagotchi.models.pet import Base


class OAuthKVStore(Base):
    """A single key-value entry, scoped to a collection, with optional TTL expiry.

    Keyed on (collection, key) — mirrors OAuthProxy's own PydanticAdapter
    stores, which each use a distinct collection name (e.g.
    "mcp-oauth-proxy-clients", "mcp-authorization-codes") against one
    shared backing store. `value` holds the already-JSON-serialized
    payload; this table doesn't need to know what's inside it.
    """

    __tablename__ = "oauth_kv_store"

    collection: Mapped[str] = mapped_column(String(255), primary_key=True)
    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
