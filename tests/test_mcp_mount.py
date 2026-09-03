"""End-to-end test that the MCP server is actually reachable through the
mounted ASGI app — not just that its tool functions work in isolation.

Regression test: `app.mount("/mcp", mcp_app)` alone is not enough. FastMCP's
StreamableHTTPSessionManager needs its own lifespan entered too, or every
request 500s with "task group was not initialized". The `client` fixture
runs the real app through TestClient as a context manager, so it exercises
the actual lifespan wiring in main.py — unlike tests/services/test_mcp_server.py,
which calls tool functions directly via `.fn` and never touches the mount.
"""

from fastapi.testclient import TestClient


def test_mcp_endpoint_responds_to_initialize(client: TestClient) -> None:
    """POSTing a real MCP initialize handshake to /mcp/mcp must not 500."""
    response = client.post(
        "/mcp/mcp",
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
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200
    assert "mcp-session-id" in response.headers
    assert '"serverInfo"' in response.text
    assert "GitHub Tamagotchi" in response.text
