"""End-to-end tests that the MCP server is actually reachable, authenticated,
and ownership-scoped through the real mounted ASGI app — not just that its
tool functions behave correctly in isolation (see
tests/services/test_mcp_server.py for that, which is faster but mocks
authentication rather than proving the real bearer-token chain works).
"""

import asyncio
from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from github_tamagotchi.models.mcp_token import McpToken
from github_tamagotchi.models.user import User
from github_tamagotchi.services.mcp_auth import generate_raw_token, hash_token
from tests.conftest import test_session_factory


def _create_user_and_token(user_id: int, github_login: str) -> str:
    """Create a real user + hashed McpToken row, return the raw token."""
    raw = generate_raw_token()

    async def _setup() -> None:
        async with test_session_factory() as session:
            session.add(User(id=user_id, github_id=user_id * 1000, github_login=github_login))
            await session.commit()
            session.add(McpToken(user_id=user_id, token_hash=hash_token(raw)))
            await session.commit()

    asyncio.run(_setup())
    return raw


@pytest.fixture
def real_db_for_mcp() -> Iterator[None]:
    """McpTokenVerifier and the MCP tools both call async_session_factory()
    directly (bypassing FastAPI's overridable get_session dependency), so it
    has to be patched to the test database for real end-to-end auth to work
    against the SQLite test DB rather than the app's real DATABASE_URL."""
    with (
        patch("github_tamagotchi.mcp.server.async_session_factory", test_session_factory),
        patch("github_tamagotchi.services.mcp_auth.async_session_factory", test_session_factory),
    ):
        yield


def _rpc(method: str, params: dict | None = None, id_: int | None = 1) -> dict:
    body: dict = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        body["id"] = id_
    if params is not None:
        body["params"] = params
    return body


_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _initialize(client: TestClient, headers: dict) -> tuple[int, dict]:
    resp = client.post(
        "/mcp",
        json=_rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-probe", "version": "0"},
            },
        ),
        headers=headers,
    )
    session_headers = dict(headers)
    if "mcp-session-id" in resp.headers:
        session_headers["mcp-session-id"] = resp.headers["mcp-session-id"]
    return resp.status_code, session_headers


class TestUnauthenticated:
    def test_no_token_is_rejected(self, client: TestClient) -> None:
        status, _ = _initialize(client, _MCP_HEADERS)
        assert status == 401

    def test_bogus_token_is_rejected(self, client: TestClient, real_db_for_mcp: None) -> None:
        headers = {**_MCP_HEADERS, "Authorization": "Bearer tama_not_a_real_token"}
        status, _ = _initialize(client, headers)
        assert status == 401


class TestAuthenticated:
    def test_valid_token_can_initialize(self, client: TestClient, real_db_for_mcp: None) -> None:
        raw = _create_user_and_token(1, "alice")
        headers = {**_MCP_HEADERS, "Authorization": f"Bearer {raw}"}

        status, _ = _initialize(client, headers)
        assert status == 200

    def test_list_pets_is_scoped_to_the_token_owner(
        self, client: TestClient, real_db_for_mcp: None
    ) -> None:
        """The real end-to-end proof that auth resolves to the right user:
        alice's token only ever sees alice's pets over the actual HTTP call,
        not bob's — even though bob has one too."""
        from github_tamagotchi.models.pet import Pet

        async def _seed() -> None:
            async with test_session_factory() as session:
                session.add(Pet(repo_owner="alice", repo_name="mine", name="Mine", user_id=1))
                session.add(Pet(repo_owner="bob", repo_name="theirs", name="Theirs", user_id=2))
                await session.commit()

        raw_alice = _create_user_and_token(1, "alice")
        _create_user_and_token(2, "bob")
        asyncio.run(_seed())

        headers = {**_MCP_HEADERS, "Authorization": f"Bearer {raw_alice}"}
        status, session_headers = _initialize(client, headers)
        assert status == 200
        client.post(
            "/mcp", json=_rpc("notifications/initialized", id_=None), headers=session_headers
        )

        resp = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "list_pets", "arguments": {}}, id_=2),
            headers=session_headers,
        )
        assert resp.status_code == 200
        assert "Mine" in resp.text
        assert "Theirs" not in resp.text


def test_mcp_endpoint_has_no_double_path(client: TestClient) -> None:
    """/mcp must work directly with no redirect (previously /mcp/mcp)."""
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers=_MCP_HEADERS,
        follow_redirects=False,
    )
    assert response.status_code != 307
    assert response.status_code != 308


def test_root_mcp_mount_does_not_shadow_other_routes(client: TestClient) -> None:
    """Mounting the MCP app at "/" must not swallow the app's other routes."""
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/leaderboard").status_code == 200
    assert client.get("/this-route-does-not-exist").status_code == 404
