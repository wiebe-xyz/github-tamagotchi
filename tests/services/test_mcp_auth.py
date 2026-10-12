"""Tests for the MCP OAuth provider's session lifetime (mcp/auth.py).

The goal these tests pin down: once an MCP client has connected, it keeps
working for months without a new browser login. Access tokens stay short;
refresh tokens slide forward on every use; everything lives in the database
so a restart or blue/green switch changes nothing; and deleting a row still
revokes.

Every test drives a real LongLivedGitHubProvider against the real
SQLite-backed DatabaseKeyValueStore. Only GitHub's API is mocked (respx),
and the clock is a patched time.time so "a year later" is instant.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastmcp.server.auth.oauth_proxy import ClientCode
from mcp.server.auth.provider import AuthorizationCode, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.mcp.auth import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_REUSE_GRACE_SECONDS,
    REFRESH_TOKEN_IDLE_TTL_SECONDS,
    LongLivedGitHubProvider,
)
from github_tamagotchi.models.oauth_kv_store import OAuthKVStore
from github_tamagotchi.models.user import User
from github_tamagotchi.services.oauth_kv_store import DatabaseKeyValueStore
from github_tamagotchi.services.token_encryption import encrypt_token
from tests.conftest import test_session_factory

DAY = 24 * 60 * 60
SCOPES = ["repo", "read:user", "read:org"]
GITHUB_USER = {"id": 4242, "login": "octo", "name": "Octo Cat", "avatar_url": "https://a/x.png"}
CLIENT = OAuthClientInformationFull(
    client_id="claude-code-client",
    redirect_uris=[AnyUrl("http://localhost:33418/callback")],
    token_endpoint_auth_method="none",
)
TEST_FERNET_KEY = Fernet.generate_key().decode()


class Clock:
    """A controllable time.time()."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Iterator[Clock]:
    c = Clock()
    with patch("time.time", side_effect=lambda: c.now):
        yield c


@pytest.fixture(autouse=True)
def _encryption_key() -> Iterator[None]:
    with patch("github_tamagotchi.core.config.settings.token_encryption_key", TEST_FERNET_KEY):
        yield


@pytest.fixture
def github() -> Iterator[respx.MockRouter]:
    """GitHub's /user endpoint: any token starting with "gho_valid" is valid."""
    with respx.mock(assert_all_called=False) as router:

        def _user(request: httpx.Request) -> httpx.Response:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer gho_valid"):
                return httpx.Response(
                    200, json=GITHUB_USER, headers={"X-OAuth-Scopes": "repo, read:org, read:user"}
                )
            return httpx.Response(401, json={"message": "Bad credentials"})

        router.get("https://api.github.com/user").mock(side_effect=_user)
        yield router


def _provider() -> LongLivedGitHubProvider:
    """A fresh provider instance over the shared test database: building a
    second one is the "process restart" (new pod, same Postgres)."""
    provider = LongLivedGitHubProvider(
        client_id="test-github-oauth-client-id",
        client_secret="test-github-oauth-client-secret",
        base_url="https://tamagotchi.test",
        redirect_path="/mcp/auth/callback",
        required_scopes=SCOPES,
        client_storage=DatabaseKeyValueStore(session_factory=test_session_factory),
        session_factory=test_session_factory,
    )
    provider.set_mcp_path("/mcp")
    return provider


async def _login(
    provider: LongLivedGitHubProvider, github_token: str = "gho_valid_1"
) -> OAuthToken:
    """Run the tail of the authorization-code flow: the upstream GitHub
    callback has stored a ClientCode, and the client now exchanges it."""
    code = f"code-{github_token}-{time.time()}"
    await provider._code_store.put(
        key=code,
        value=ClientCode(
            code=code,
            client_id=CLIENT.client_id or "",
            redirect_uri="http://localhost:33418/callback",
            code_challenge="challenge",
            code_challenge_method="S256",
            scopes=SCOPES,
            idp_tokens={"access_token": github_token, "token_type": "bearer", "scope": "repo"},
            expires_at=time.time() + 300,
            created_at=time.time(),
        ),
        ttl=300,
    )
    return await provider.exchange_authorization_code(
        CLIENT,
        AuthorizationCode(
            code=code,
            scopes=SCOPES,
            expires_at=time.time() + 300,
            client_id=CLIENT.client_id or "",
            code_challenge="challenge",
            redirect_uri=AnyUrl("http://localhost:33418/callback"),
            redirect_uri_provided_explicitly=True,
        ),
    )


async def _refresh(provider: LongLivedGitHubProvider, refresh_token: str) -> OAuthToken:
    """Do what the MCP SDK's /token handler does for grant_type=refresh_token."""
    loaded = await provider.load_refresh_token(CLIENT, refresh_token)
    if loaded is None:
        raise TokenError("invalid_grant", "refresh token does not exist")
    if loaded.expires_at and loaded.expires_at < time.time():
        raise TokenError("invalid_grant", "refresh token has expired")
    return await provider.exchange_refresh_token(CLIENT, loaded, loaded.scopes)


# ---------------------------------------------------------------------------
# Lifetimes
# ---------------------------------------------------------------------------


async def test_login_issues_short_access_token_and_refresh_token(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    tokens = await _login(_provider())

    assert tokens.refresh_token is not None
    assert tokens.expires_in == ACCESS_TOKEN_TTL_SECONDS
    assert 60 * 60 <= ACCESS_TOKEN_TTL_SECONDS <= DAY
    assert REFRESH_TOKEN_IDLE_TTL_SECONDS >= 365 * DAY


async def test_access_token_authenticates_with_github_identity(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)

    access = await provider.load_access_token(tokens.access_token)

    assert access is not None
    assert access.token == "gho_valid_1"  # tools get the user's GitHub token
    assert access.claims["sub"] == "4242"
    assert access.claims["login"] == "octo"
    assert set(SCOPES) <= set(access.scopes)


async def test_access_token_expires(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)

    clock.advance(ACCESS_TOKEN_TTL_SECONDS + 1)

    assert await provider.load_access_token(tokens.access_token) is None


async def test_refresh_token_is_not_accepted_as_access_token(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    assert await provider.load_access_token(tokens.refresh_token) is None


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


async def test_refresh_works_after_access_token_expires(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    clock.advance(ACCESS_TOKEN_TTL_SECONDS + 1)
    assert await provider.load_access_token(tokens.access_token) is None

    refreshed = await _refresh(provider, tokens.refresh_token)

    access = await provider.load_access_token(refreshed.access_token)
    assert access is not None
    assert access.claims["login"] == "octo"
    assert refreshed.refresh_token is not None
    assert refreshed.refresh_token != tokens.refresh_token  # rotated


async def test_refresh_token_survives_restart(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    tokens = await _login(_provider())
    assert tokens.refresh_token is not None

    # New process, same database: nothing held in memory carries over.
    clock.advance(3 * DAY)
    restarted = _provider()

    refreshed = await restarted.exchange_refresh_token(
        CLIENT,
        await _load(restarted, tokens.refresh_token),
        SCOPES,
    )
    assert await restarted.load_access_token(refreshed.access_token) is not None


async def test_access_token_survives_restart(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    tokens = await _login(_provider())

    assert await _provider().load_access_token(tokens.access_token) is not None


async def test_sliding_expiry_extends_on_use(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    # Used regularly, the session outlives any fixed lifetime counted from login.
    current = tokens.refresh_token
    for _ in range(4):
        clock.advance(300 * DAY)
        refreshed = await _refresh(provider, current)
        assert refreshed.refresh_token is not None
        current = refreshed.refresh_token

    # 1200 days after login, still connected.
    assert await provider.load_access_token(refreshed.access_token) is not None


async def test_idle_session_expires_after_idle_ttl(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    clock.advance(REFRESH_TOKEN_IDLE_TTL_SECONDS + DAY)

    with pytest.raises(TokenError):
        await _refresh(provider, tokens.refresh_token)


async def test_concurrent_refresh_within_grace_window_succeeds(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    first = await _refresh(provider, tokens.refresh_token)
    clock.advance(REFRESH_REUSE_GRACE_SECONDS / 2)
    second = await _refresh(provider, tokens.refresh_token)

    # Both callers end up with a working session.
    assert await provider.load_access_token(first.access_token) is not None
    assert await provider.load_access_token(second.access_token) is not None
    assert second.refresh_token is not None
    assert await _refresh(provider, second.refresh_token) is not None


async def test_reuse_after_grace_window_revokes_the_grant(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    first = await _refresh(provider, tokens.refresh_token)
    clock.advance(REFRESH_REUSE_GRACE_SECONDS + 1)

    with pytest.raises(TokenError):
        await _refresh(provider, tokens.refresh_token)

    # A replayed, rotated refresh token is treated as stolen: the whole
    # grant goes, including the tokens the legitimate holder got.
    assert await provider.load_access_token(first.access_token) is None


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


async def test_deleting_grant_row_revokes_access_and_refresh(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    async with test_session_factory() as session:
        await session.execute(delete(OAuthKVStore).where(OAuthKVStore.collection == "mcp-grants"))
        await session.commit()

    assert await provider.load_access_token(tokens.access_token) is None
    with pytest.raises(TokenError):
        await _refresh(provider, tokens.refresh_token)


async def test_deleting_refresh_token_row_revokes_refresh(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    async with test_session_factory() as session:
        await session.execute(
            delete(OAuthKVStore).where(OAuthKVStore.collection == "mcp-session-refresh-tokens")
        )
        await session.commit()

    with pytest.raises(TokenError):
        await _refresh(provider, tokens.refresh_token)


# ---------------------------------------------------------------------------
# Upstream GitHub token
# ---------------------------------------------------------------------------


async def test_github_token_is_encrypted_at_rest(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    await _login(_provider(), github_token="gho_valid_secret")

    async with test_session_factory() as session:
        rows = (await session.execute(select(OAuthKVStore.value))).scalars().all()
    assert not any("gho_valid_secret" in value for value in rows)


async def test_revoked_github_token_is_replaced_by_newer_website_login_token(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    """GitHub keeps at most ten tokens per user/app/scope and revokes the
    oldest. The website login uses the same OAuth App and scopes, so ten
    website logins revoke the MCP session's GitHub token. The session must
    pick up the newer token instead of forcing a new MCP login."""
    provider = _provider()
    tokens = await _login(provider, github_token="gho_valid_old")
    assert tokens.refresh_token is not None

    # The MCP token gets revoked; the website stored a newer one.
    github.routes.clear()

    def _user(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") == "Bearer gho_valid_new":
            return httpx.Response(200, json=GITHUB_USER, headers={"X-OAuth-Scopes": "repo"})
        return httpx.Response(401, json={"message": "Bad credentials"})

    github.get("https://api.github.com/user").mock(side_effect=_user)
    async with test_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.github_id == GITHUB_USER["id"]))
        ).scalar_one()
        user.encrypted_token = encrypt_token("gho_valid_new")
        await session.commit()

    clock.advance(ACCESS_TOKEN_TTL_SECONDS + 1)
    refreshed = await _refresh(provider, tokens.refresh_token)

    access = await provider.load_access_token(refreshed.access_token)
    assert access is not None
    assert access.token == "gho_valid_new"


async def test_revoked_github_token_without_replacement_ends_session(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    """If the user revoked the app on GitHub, no valid token exists anywhere,
    and the MCP session must end at the next refresh."""
    provider = _provider()
    tokens = await _login(provider, github_token="gho_valid_old")
    assert tokens.refresh_token is not None

    github.routes.clear()
    github.get("https://api.github.com/user").mock(
        return_value=httpx.Response(401, json={"message": "Bad credentials"})
    )

    with pytest.raises(TokenError):
        await _refresh(provider, tokens.refresh_token)


async def test_github_outage_does_not_end_session(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    assert tokens.refresh_token is not None

    github.routes.clear()
    github.get("https://api.github.com/user").mock(side_effect=httpx.ConnectError("down"))

    refreshed = await _refresh(provider, tokens.refresh_token)
    assert await provider.load_access_token(refreshed.access_token) is not None


async def test_access_token_check_does_not_call_github(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    provider = _provider()
    tokens = await _login(provider)
    calls_after_login = github.calls.call_count

    for _ in range(5):
        assert await provider.load_access_token(tokens.access_token) is not None

    assert github.calls.call_count == calls_after_login


async def test_mcp_login_stores_github_token_on_user(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    await _login(_provider(), github_token="gho_valid_fresh")

    async with test_session_factory() as session:
        user = (
            await session.execute(select(User).where(User.github_id == GITHUB_USER["id"]))
        ).scalar_one()
    assert user.encrypted_token is not None
    assert "gho_valid_fresh" not in user.encrypted_token


async def test_login_with_invalid_github_token_fails(
    test_db: AsyncSession, clock: Clock, github: respx.MockRouter
) -> None:
    with pytest.raises(TokenError):
        await _login(_provider(), github_token="gho_bogus")


async def _load(provider: LongLivedGitHubProvider, refresh_token: str) -> Any:
    loaded = await provider.load_refresh_token(CLIENT, refresh_token)
    assert loaded is not None
    return loaded
