"""Tests for API routes."""

from fastapi.testclient import TestClient

from github_tamagotchi import __version__


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """Health endpoint should return 200 OK."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_returns_healthy_status(self, client: TestClient) -> None:
        """Health endpoint should return healthy status."""
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["status"] == "healthy"

    def test_health_returns_version(self, client: TestClient) -> None:
        """Health endpoint should return current version."""
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["version"] == __version__


class TestPetsEndpoints:
    """Tests for pet management endpoints."""

    def test_create_pet_validates_input(self, client: TestClient) -> None:
        """Create pet endpoint should validate required fields."""
        response = client.post("/api/v1/pets", json={})
        assert response.status_code == 422  # Validation error

    def test_create_pet_validates_missing_name(self, client: TestClient) -> None:
        """Create pet endpoint should require name field."""
        response = client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo"},
        )
        assert response.status_code == 422

    def test_get_pet_not_found_returns_404(self, client: TestClient) -> None:
        """Get pet endpoint should return 404 for non-existent pet."""
        response = client.get("/api/v1/pets/nonexistent/repo")
        assert response.status_code == 404

    def test_feed_pet_not_found_returns_404(self, client: TestClient) -> None:
        """Feed pet endpoint should return 404 for non-existent pet."""
        response = client.post("/api/v1/pets/nonexistent/repo/feed")
        assert response.status_code == 404

    def test_delete_pet_not_found_returns_404(self, client: TestClient) -> None:
        """Delete pet endpoint should return 404 for non-existent pet."""
        response = client.delete("/api/v1/pets/nonexistent/repo")
        assert response.status_code == 404

    def test_list_pets_returns_200(self, client: TestClient) -> None:
        """List pets endpoint should return 200 OK."""
        response = client.get("/api/v1/pets")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
