"""E2E tests for the GitHub login flow.

Verifies that the login button on the landing page leads to a working
OAuth flow rather than a 404.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.database import get_session

from .conftest import get_e2e_session


def create_full_app() -> FastAPI:
    """Create the full app (with templates, static, all routes) for E2E testing."""
    import importlib
    import sys

    # Ensure fresh import of main to get the real app
    if "github_tamagotchi.main" in sys.modules:
        del sys.modules["github_tamagotchi.main"]

    main = importlib.import_module("github_tamagotchi.main")

    # Create a test version without scheduler/worker
    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(
        title=main.app.title,
        version=main.app.version,
        lifespan=test_lifespan,
    )

    # Include all routers from the real app
    for route in main.app.routes:
        app.routes.append(route)

    app.dependency_overrides[get_session] = get_e2e_session
    return app


class TestGitHubLoginFlow:
    """Tests for the GitHub OAuth login flow."""

    @pytest.fixture
    async def full_client(self, e2e_db: AsyncSession) -> AsyncIterator[AsyncClient]:
        """AsyncClient wired to the full app."""
        app = create_full_app()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://e2e",
            follow_redirects=False,
        ) as client:
            yield client

    async def test_landing_page_has_login_link(self, full_client: AsyncClient) -> None:
        """Landing page should contain a login link."""
        response = await full_client.get("/")
        assert response.status_code == 200
        assert "/auth/github" in response.text

    async def test_login_endpoint_exists(self, full_client: AsyncClient) -> None:
        """GET /auth/github should not return 404."""
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = "test-client-id"
            mock_settings.oauth_redirect_uri = "http://e2e/auth/callback"
            response = await full_client.get("/auth/github")
        assert response.status_code != 404, (
            "/auth/github returns 404 — GitHub OAuth flow is not implemented. See issue #8."
        )

    async def test_login_redirects_to_github(self, full_client: AsyncClient) -> None:
        """GET /auth/github should redirect to GitHub's OAuth authorize URL."""
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = "test-client-id"
            mock_settings.oauth_redirect_uri = "http://e2e/auth/callback"
            response = await full_client.get("/auth/github")
        assert response.status_code in (302, 307), (
            f"/auth/github should redirect to GitHub OAuth, got status {response.status_code}"
        )
        location = response.headers.get("location", "")
        assert "github.com" in location, f"Expected redirect to github.com, got: {location}"

    async def test_oauth_callback_endpoint_exists(self, full_client: AsyncClient) -> None:
        """GET /auth/callback should exist for the OAuth return flow."""
        response = await full_client.get("/auth/callback")
        # Without a valid code param it should return 400/422, not 404
        assert response.status_code != 404, (
            "/auth/callback returns 404 — OAuth callback not implemented"
        )
