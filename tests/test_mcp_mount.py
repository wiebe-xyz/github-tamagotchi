"""End-to-end tests that the MCP server is actually reachable and correctly
gated behind real GitHub OAuth through the mounted ASGI app — not just that
its tool functions behave correctly in isolation (see
tests/services/test_mcp_server.py for that: it covers ownership scoping,
the feed/weight mechanic, play cooldown, and leaderboard by patching auth
resolution the way the real layer populates it, which is both faster and
more thorough than driving those cases through raw HTTP).

What's deliberately NOT covered here: a full "authenticated tool call"
round-trip over raw HTTP. FastMCP's OAuthProxy mints and verifies its own
JWT for the client-facing token rather than passing the upstream GitHub
token straight through, so faithfully simulating that here would mean
either reimplementing real JWT minting or walking the full
register -> authorize -> (mocked) GitHub redirect -> callback -> token
exchange sequence — fragile to write against a third-party library's
internals and not where the real risk in this feature lives (that risk is
ownership scoping, which test_mcp_server.py already covers thoroughly).
What *is* covered here, and is exactly what regressed for the reported
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
