"""End-to-end tests that the MCP server is actually reachable and correctly
gated behind real GitHub OAuth through the mounted ASGI app — not just that
its tool functions behave correctly in isolation (see
tests/services/test_mcp_server.py for that: it covers ownership scoping,
the feed/weight mechanic, play cooldown, and leaderboard by patching auth
resolution the way the real layer populates it, which is both faster and
more thorough than driving those cases through raw HTTP).

test_full_token_lifecycle_over_http walks register -> code exchange ->
/mcp -> access token expiry -> refresh -> /mcp over raw HTTP, skipping only
the GitHub redirect. Also covered here, and is exactly what regressed for the reported
bug: the OAuth discovery/DCR endpoints a real client tries actually exist
and respond, and a request with no/invalid credentials is rejected.
"""

from fastapi.testclient import TestClient

_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _initialize(client: TestClient, headers: dict) -> int:
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-probe", "version": "0"},
            },
        },
        headers=headers,
    )
    return resp.status_code


class TestUnauthenticated:
    def test_no_token_is_rejected(self, client: TestClient) -> None:
        assert _initialize(client, _MCP_HEADERS) == 401

    def test_bogus_token_is_rejected(self, client: TestClient) -> None:
        headers = {**_MCP_HEADERS, "Authorization": "Bearer not-a-real-token"}
        assert _initialize(client, headers) == 401


class TestOAuthDiscovery:
    """Regression coverage for the reported bug: Claude Code tried Dynamic
    Client Registration against this server and got HTTP 404 on every
    discovery endpoint it probed, because the MCP server only verified
    pre-issued bearer tokens with no way to actually get one interactively.
    These must all resolve now that auth is a real GitHubProvider OAuth
    proxy (FastMCP's DCR-emulation layer for upstream providers, like
    GitHub, that don't support DCR themselves)."""

    def test_oauth_authorization_server_metadata(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        body = resp.json()
        assert "authorization_endpoint" in body
        assert "registration_endpoint" in body

    def test_protected_resource_metadata(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-protected-resource/mcp")
        assert resp.status_code == 200

    def test_dynamic_client_registration(self, client: TestClient) -> None:
        """The exact call that 404'd before: POST /register."""
        resp = client.post(
            "/register",
            json={"redirect_uris": ["http://localhost:1234/callback"]},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "client_id" in body

    def test_authorize_endpoint_exists(self, client: TestClient) -> None:
        """Not asserting a full redirect dance here, just that this route
        exists at all (previously 404) rather than erroring on missing
        required query params."""
        resp = client.get("/authorize", follow_redirects=False)
        assert resp.status_code != 404


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


def test_mcp_info_page_is_reachable_without_auth(client: TestClient) -> None:
    """The unauthenticated landing page explaining how to connect."""
    response = client.get("/mcp/info")
    assert response.status_code == 200
    assert "claude mcp add" in response.text
    assert "/mcp" in response.text


def test_full_token_lifecycle_over_http(client: TestClient) -> None:
    """Register, exchange a code, call /mcp, let the access token expire,
    refresh at /token, and call /mcp again, all through the mounted app.

    Only the GitHub redirect is skipped: the authorization code GitHub's
    callback would store is written straight into the provider's code
    store. See tests/services/test_mcp_auth.py for the lifetime rules.
    """
    import base64
    import hashlib
    import time
    from unittest.mock import patch

    import httpx
    import respx
    from fastmcp.server.auth.oauth_proxy import ClientCode

    from github_tamagotchi.mcp import server as mcp_server_module
    from github_tamagotchi.mcp.auth import ACCESS_TOKEN_TTL_SECONDS

    provider = mcp_server_module.mcp.auth
    assert provider is not None

    redirect_uri = "http://localhost:1234/callback"
    reg = client.post(
        "/register",
        json={"redirect_uris": [redirect_uri], "token_endpoint_auth_method": "none"},
    )
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]

    verifier = "v" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    scopes = ["repo", "read:user", "read:org"]

    async def _seed_code() -> None:
        await provider._code_store.put(  # type: ignore[attr-defined]
            key="e2e-code",
            value=ClientCode(
                code="e2e-code",
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_challenge=challenge,
                code_challenge_method="S256",
                scopes=scopes,
                idp_tokens={"access_token": "gho_e2e", "token_type": "bearer"},
                expires_at=time.time() + 300,
                created_at=time.time(),
            ),
            ttl=300,
        )

    assert client.portal is not None
    client.portal.call(_seed_code)

    github_user = {"id": 99, "login": "e2e-user", "avatar_url": None}
    with respx.mock() as router:
        router.get("https://api.github.com/user").mock(
            return_value=httpx.Response(
                200, json=github_user, headers={"X-OAuth-Scopes": "repo, read:user, read:org"}
            )
        )

        token_resp = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": "e2e-code",
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert token_resp.status_code == 200, token_resp.text
        tokens = token_resp.json()
        assert tokens["expires_in"] == ACCESS_TOKEN_TTL_SECONDS
        assert tokens["refresh_token"]

        bearer = {**_MCP_HEADERS, "Authorization": f"Bearer {tokens['access_token']}"}
        assert _initialize(client, bearer) == 200

        later = time.time() + ACCESS_TOKEN_TTL_SECONDS + 60
        with patch("time.time", return_value=later):
            assert _initialize(client, bearer) == 401

            refresh_resp = client.post(
                "/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": tokens["refresh_token"],
                    "client_id": client_id,
                },
            )
            assert refresh_resp.status_code == 200, refresh_resp.text
            refreshed = refresh_resp.json()
            assert refreshed["refresh_token"] != tokens["refresh_token"]

            new_bearer = {**_MCP_HEADERS, "Authorization": f"Bearer {refreshed['access_token']}"}
            assert _initialize(client, new_bearer) == 200
