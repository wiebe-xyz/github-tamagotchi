"""Tests for personal API token management (used to authenticate MCP clients)."""

import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import select

from github_tamagotchi.api.auth import _create_jwt
from github_tamagotchi.models.mcp_token import McpToken
from github_tamagotchi.models.user import User
from github_tamagotchi.services.mcp_auth import hash_token
from tests.conftest import test_session_factory


def _create_user(user_id: int, github_login: str) -> str:
    async def _setup() -> str:
        async with test_session_factory() as session:
            user = User(id=user_id, github_id=user_id * 1000, github_login=github_login)
            session.add(user)
            await session.commit()
        return _create_jwt(user_id=user_id)

    return asyncio.run(_setup())


class TestCreateToken:
    def test_requires_login(self, client: TestClient) -> None:
        resp = client.post("/api/v1/mcp-tokens", json={})
        assert resp.status_code == 401

    def test_creates_and_returns_raw_token_once(self, client: TestClient) -> None:
        jwt = _create_user(1, "alice")
        resp = client.post(
            "/api/v1/mcp-tokens",
            json={"label": "my laptop"},
            cookies={"session_token": jwt},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["label"] == "my laptop"
        assert body["token"].startswith("tama_")

    def test_stores_only_the_hash(self, client: TestClient) -> None:
        jwt = _create_user(1, "alice")
        resp = client.post("/api/v1/mcp-tokens", json={}, cookies={"session_token": jwt})
        raw_token = resp.json()["token"]

        async def _check() -> None:
            async with test_session_factory() as session:
                result = await session.execute(select(McpToken))
                tokens = result.scalars().all()
                assert len(tokens) == 1
                assert tokens[0].token_hash == hash_token(raw_token)
                assert raw_token not in tokens[0].token_hash

        asyncio.run(_check())


class TestListTokens:
    def test_requires_login(self, client: TestClient) -> None:
        assert client.get("/api/v1/mcp-tokens").status_code == 401

    def test_lists_own_tokens_without_raw_value(self, client: TestClient) -> None:
        jwt = _create_user(1, "alice")
        client.post("/api/v1/mcp-tokens", json={"label": "token-a"}, cookies={"session_token": jwt})
        client.post("/api/v1/mcp-tokens", json={"label": "token-b"}, cookies={"session_token": jwt})

        resp = client.get("/api/v1/mcp-tokens", cookies={"session_token": jwt})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert {t["label"] for t in body} == {"token-a", "token-b"}
        assert all("token" not in t for t in body)

    def test_only_shows_own_tokens(self, client: TestClient) -> None:
        jwt_a = _create_user(1, "alice")
        jwt_b = _create_user(2, "bob")
        client.post(
            "/api/v1/mcp-tokens", json={"label": "alice-token"}, cookies={"session_token": jwt_a}
        )

        resp = client.get("/api/v1/mcp-tokens", cookies={"session_token": jwt_b})
        assert resp.json() == []


class TestRevokeToken:
    def test_owner_can_revoke(self, client: TestClient) -> None:
        jwt = _create_user(1, "alice")
        created = client.post("/api/v1/mcp-tokens", json={}, cookies={"session_token": jwt}).json()

        resp = client.delete(f"/api/v1/mcp-tokens/{created['id']}", cookies={"session_token": jwt})
        assert resp.status_code == 204

        listing = client.get("/api/v1/mcp-tokens", cookies={"session_token": jwt}).json()
        assert listing == []

    def test_cannot_revoke_someone_elses_token(self, client: TestClient) -> None:
        jwt_a = _create_user(1, "alice")
        jwt_b = _create_user(2, "bob")
        created = client.post(
            "/api/v1/mcp-tokens", json={}, cookies={"session_token": jwt_a}
        ).json()

        resp = client.delete(
            f"/api/v1/mcp-tokens/{created['id']}", cookies={"session_token": jwt_b}
        )
        assert resp.status_code == 404

        # Still there for its actual owner.
        listing = client.get("/api/v1/mcp-tokens", cookies={"session_token": jwt_a}).json()
        assert len(listing) == 1
