"""Tests for landing page."""

from fastapi.testclient import TestClient


class TestLandingPage:
    """Tests for the landing page."""

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
        """Landing page should contain login with GitHub CTA."""
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
