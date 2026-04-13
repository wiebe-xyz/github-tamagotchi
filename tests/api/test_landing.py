"""Tests for landing page."""

import asyncio

from fastapi.testclient import TestClient

from github_tamagotchi.api.auth import _create_jwt
from github_tamagotchi.models.user import User
from tests.conftest import test_session_factory


class TestLandingPage:
    """Tests for the landing page (unauthenticated)."""

    def test_returns_html(self, client: TestClient) -> None:
        """Landing page should return HTML content."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_contains_title(self, client: TestClient) -> None:
        """Landing page should contain the app title."""
        response = client.get("/")
        assert "GitHub Tamagotchi" in response.text

    def test_contains_login_cta(self, client: TestClient) -> None:
        """Landing page should contain login with GitHub CTA when not logged in."""
        response = client.get("/")
        assert "Login with GitHub" in response.text

    def test_contains_how_it_works(self, client: TestClient) -> None:
        """Landing page should contain How It Works section."""
        response = client.get("/")
        assert "How It Works" in response.text

    def test_contains_connect_repo_step(self, client: TestClient) -> None:
        """Landing page should explain connecting repo."""
        response = client.get("/")
        assert "Connect Your Repo" in response.text

    def test_contains_keep_coding_step(self, client: TestClient) -> None:
        """Landing page should explain coding benefits."""
        response = client.get("/")
        assert "Keep Coding" in response.text

    def test_contains_evolution_step(self, client: TestClient) -> None:
        """Landing page should explain pet evolution."""
        response = client.get("/")
        assert "Watch It Evolve" in response.text

    def test_contains_mcp_mention(self, client: TestClient) -> None:
        """Landing page should mention MCP integration."""
        response = client.get("/")
        assert "MCP" in response.text

    def test_no_logout_button_when_unauthenticated(self, client: TestClient) -> None:
        """Landing page should not show logout button when not logged in."""
        response = client.get("/")
        assert "Log out" not in response.text

    def test_no_user_links_when_unauthenticated(self, client: TestClient) -> None:
        """Landing page should not show user-specific nav links when not logged in."""
        response = client.get("/")
        assert "/dashboard" not in response.text
        assert "/register" not in response.text


class TestLandingPageAuthenticated:
    """Tests for the landing page when logged in."""

    def _create_user_and_token(self) -> str:
        """Create a test user in the DB and return a valid JWT."""

        async def _setup() -> str:
            async with test_session_factory() as session:
                user = User(
                    id=1,
                    github_id=12345,
                    github_login="testuser",
                    github_avatar_url="https://avatars.example.com/testuser",
                )
                session.add(user)
                await session.commit()
            return _create_jwt(user_id=1)

        return asyncio.run(_setup())

    def test_shows_username_when_authenticated(self, client: TestClient) -> None:
        """Landing page should show username when logged in."""
        token = self._create_user_and_token()
        response = client.get("/", cookies={"session_token": token})
        assert "testuser" in response.text

    def test_shows_avatar_when_authenticated(self, client: TestClient) -> None:
        """Landing page should show avatar when logged in."""
        token = self._create_user_and_token()
        response = client.get("/", cookies={"session_token": token})
        assert "https://avatars.example.com/testuser" in response.text

    def test_shows_logout_button_when_authenticated(self, client: TestClient) -> None:
        """Landing page should show logout button when logged in."""
        token = self._create_user_and_token()
        response = client.get("/", cookies={"session_token": token})
        assert "Log out" in response.text

    def test_hides_login_cta_when_authenticated(self, client: TestClient) -> None:
        """Landing page should hide login buttons when logged in."""
        token = self._create_user_and_token()
        response = client.get("/", cookies={"session_token": token})
        assert "Login with GitHub" not in response.text

    def test_shows_user_nav_when_authenticated(self, client: TestClient) -> None:
        """Landing page should show user nav when logged in."""
        token = self._create_user_and_token()
        response = client.get("/", cookies={"session_token": token})
        assert "user-nav" in response.text


class TestStaticFiles:
    """Tests for static file serving."""

    def test_css_accessible(self, client: TestClient) -> None:
        """Static CSS file should be accessible."""
        response = client.get("/static/css/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_css_contains_styles(self, client: TestClient) -> None:
        """CSS file should contain actual styles."""
        response = client.get("/static/css/style.css")
        assert "body" in response.text
        assert "color" in response.text

    def test_missing_static_returns_404(self, client: TestClient) -> None:
        """Missing static files should return 404."""
        response = client.get("/static/nonexistent.css")
        assert response.status_code == 404
