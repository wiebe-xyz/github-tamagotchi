"""Tests for DatabaseKeyValueStore, the durable backing for FastMCP's OAuth
proxy (see mcp/server.py's _build_auth() and issue #262).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.services.oauth_kv_store import DatabaseKeyValueStore
from tests.conftest import test_session_factory as _test_session_factory


def _store() -> DatabaseKeyValueStore:
    """A store bound to the same test engine/session factory `test_db` set
    up tables on — each call opens (and closes) its own session, exercising
    real cross-session persistence rather than one shared session.
    """
    return DatabaseKeyValueStore(session_factory=_test_session_factory)


async def test_get_missing_key_returns_none(test_db: AsyncSession) -> None:
    store = _store()
    assert await store.get("nope", collection="widgets") is None


async def test_put_get_roundtrip(test_db: AsyncSession) -> None:
    store = _store()
    await store.put("client-1", {"client_id": "client-1", "scopes": ["repo"]}, collection="clients")

    result = await store.get("client-1", collection="clients")

    assert result == {"client_id": "client-1", "scopes": ["repo"]}


async def test_put_overwrites_existing_key(test_db: AsyncSession) -> None:
    store = _store()
    await store.put("client-1", {"version": 1}, collection="clients")
    await store.put("client-1", {"version": 2}, collection="clients")

    assert await store.get("client-1", collection="clients") == {"version": 2}


async def test_collections_are_isolated(test_db: AsyncSession) -> None:
    store = _store()
    await store.put("same-key", {"which": "clients"}, collection="clients")
    await store.put("same-key", {"which": "codes"}, collection="codes")

    assert await store.get("same-key", collection="clients") == {"which": "clients"}
    assert await store.get("same-key", collection="codes") == {"which": "codes"}


async def test_default_collection_used_when_omitted(test_db: AsyncSession) -> None:
    store = _store()
    await store.put("k", {"v": 1})

    assert await store.get("k") == {"v": 1}
    # Doesn't leak into an explicitly named collection.
    assert await store.get("k", collection="clients") is None


async def test_delete_removes_key_and_reports_true(test_db: AsyncSession) -> None:
    store = _store()
    await store.put("client-1", {"a": 1}, collection="clients")

    deleted = await store.delete("client-1", collection="clients")

    assert deleted is True
    assert await store.get("client-1", collection="clients") is None


async def test_delete_missing_key_returns_false(test_db: AsyncSession) -> None:
    store = _store()
    assert await store.delete("nope", collection="clients") is False


async def test_ttl_expiry_behaves_as_a_miss(test_db: AsyncSession) -> None:
    """A negative ttl is already in the past the instant it's written —
    equivalent to (and far less flaky than) sleeping past a short one.
    """
    store = _store()
    await store.put("transient", {"a": 1}, collection="codes", ttl=-1)

    assert await store.get("transient", collection="codes") is None
    value, ttl_remaining = await store.ttl("transient", collection="codes")
    assert value is None
    assert ttl_remaining is None


async def test_ttl_returns_value_and_remaining_seconds_when_not_expired(
    test_db: AsyncSession,
) -> None:
    store = _store()
    await store.put("client-1", {"a": 1}, collection="clients", ttl=3600)

    value, ttl_remaining = await store.ttl("client-1", collection="clients")

    assert value == {"a": 1}
    assert ttl_remaining is not None
    assert 0 < ttl_remaining <= 3600


async def test_ttl_of_entry_without_ttl_is_none(test_db: AsyncSession) -> None:
    store = _store()
    await store.put("client-1", {"a": 1}, collection="clients")

    value, ttl_remaining = await store.ttl("client-1", collection="clients")

    assert value == {"a": 1}
    assert ttl_remaining is None


async def test_get_many_and_delete_many(test_db: AsyncSession) -> None:
    store = _store()
    await store.put("a", {"n": 1}, collection="clients")
    await store.put("b", {"n": 2}, collection="clients")

    values = await store.get_many(["a", "b", "missing"], collection="clients")
    assert values == [{"n": 1}, {"n": 2}, None]

    deleted_count = await store.delete_many(["a", "b", "missing"], collection="clients")
    assert deleted_count == 2
    assert await store.get_many(["a", "b"], collection="clients") == [None, None]
