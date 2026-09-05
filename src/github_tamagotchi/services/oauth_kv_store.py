"""Database-backed key-value store for FastMCP's OAuth proxy.

FastMCP's GitHubProvider (a OAuthProxy subclass — see mcp/server.py's
_build_auth()) persists all of its OAuth state — registered Dynamic Client
Registration clients, in-flight authorization transactions, one-time
authorization codes, and refresh-token metadata — through a small
key-value protocol (key_value.aio.protocols.AsyncKeyValue). Left
unconfigured it falls back to an encrypted on-disk store rooted in this
process's own local filesystem: fine for a single long-lived process, but
wiped on every restart/redeploy and never shared across replicas. That's
what silently broke every previously registered MCP client whenever the
pod restarted (issue #262) — a client that registered before a restart
just stops being recognised, with no signal to the client that anything
changed.

DatabaseKeyValueStore below implements that same protocol against the
oauth_kv_store table, so registrations (and everything else OAuthProxy
stores) survive restarts and are shared across replicas, exactly like
every other piece of this app's state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, SupportsFloat

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from github_tamagotchi.core.database import async_session_factory
from github_tamagotchi.models.oauth_kv_store import OAuthKVStore

# AsyncKeyValueProtocol's collection is optional and falls back to a
# "default collection" when omitted — OAuthProxy always passes one
# explicitly (a distinct collection per kind of state), but this keeps the
# store well-behaved for any caller that doesn't.
_DEFAULT_COLLECTION = "default"


class DatabaseKeyValueStore:
    """AsyncKeyValueProtocol implementation backed by the oauth_kv_store table.

    Each entry is keyed on (collection, key); `value` is stored as JSON
    text (OAuthProxy's PydanticAdapter wrapper already hands us a plain
    JSON-serializable dict — see the pydantic-model stores it builds in
    OAuthProxy.__init__). Expiry is enforced lazily: a get()/ttl() past
    expires_at behaves as a miss and opportunistically deletes the stale
    row, rather than running a background sweep for what is, in practice,
    a low-volume store.
    """

    def __init__(self, session_factory: async_sessionmaker[Any] | None = None) -> None:
        # An explicit factory always wins. Otherwise, deliberately *don't*
        # resolve/capture the default here: this store is normally built
        # once, at MCP-server import time (see mcp/server.py's
        # _build_auth()), so capturing async_session_factory in __init__
        # would freeze in whatever engine was configured at import time —
        # long before a test could swap it out. Looking it up fresh in
        # _open_session() instead means `patch("...oauth_kv_store.
        # async_session_factory")` (see conftest.py's `client` fixture)
        # still works no matter when this instance was constructed.
        self._session_factory_override = session_factory

    def _open_session(self) -> Any:
        factory = self._session_factory_override or async_session_factory
        return factory()

    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        value, _ttl = await self.ttl(key, collection=collection)
        return value

    async def ttl(
        self, key: str, *, collection: str | None = None
    ) -> tuple[dict[str, Any] | None, float | None]:
        collection_name = collection or _DEFAULT_COLLECTION
        now = datetime.now(UTC)
        async with self._open_session() as session:
            row = await session.get(OAuthKVStore, (collection_name, key))
            if row is None:
                return None, None

            expires_at = _as_aware(row.expires_at)
            if expires_at is not None and expires_at <= now:
                await session.delete(row)
                await session.commit()
                return None, None

            remaining = (expires_at - now).total_seconds() if expires_at is not None else None
            return json.loads(row.value), remaining

    async def put(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        collection_name = collection or _DEFAULT_COLLECTION
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=float(ttl)) if ttl is not None else None
        )
        serialized = json.dumps(dict(value))

        async with self._open_session() as session:
            row = await session.get(OAuthKVStore, (collection_name, key))
            if row is not None:
                row.value = serialized
                row.expires_at = expires_at
                await session.commit()
                return

            session.add(
                OAuthKVStore(
                    collection=collection_name,
                    key=key,
                    value=serialized,
                    expires_at=expires_at,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # Lost a race with a concurrent put() of the same key —
                # fall back to updating the row that won.
                await session.rollback()
                row = await session.get(OAuthKVStore, (collection_name, key))
                if row is None:
                    raise
                row.value = serialized
                row.expires_at = expires_at
                await session.commit()

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        collection_name = collection or _DEFAULT_COLLECTION
        async with self._open_session() as session:
            row = await session.get(OAuthKVStore, (collection_name, key))
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def get_many(
        self, keys: Sequence[str], *, collection: str | None = None
    ) -> list[dict[str, Any] | None]:
        return [await self.get(key, collection=collection) for key in keys]

    async def ttl_many(
        self, keys: Sequence[str], *, collection: str | None = None
    ) -> list[tuple[dict[str, Any] | None, float | None]]:
        return [await self.ttl(key, collection=collection) for key in keys]

    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        for key, value in zip(keys, values, strict=True):
            await self.put(key, value, collection=collection, ttl=ttl)

    async def delete_many(self, keys: Sequence[str], *, collection: str | None = None) -> int:
        deleted = 0
        for key in keys:
            if await self.delete(key, collection=collection):
                deleted += 1
        return deleted


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite (used in tests) hands back naive datetimes even for
    DateTime(timezone=True) columns; Postgres doesn't. Normalize to UTC-aware
    so comparisons against datetime.now(UTC) never raise or silently compare
    wrong.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)
