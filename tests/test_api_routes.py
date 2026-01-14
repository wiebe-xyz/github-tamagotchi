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

    def test_create_pet_not_implemented(self, client: TestClient) -> None:
        """Create pet endpoint should return 501 until implemented."""
        response = client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "TestPet"},
        )
        assert response.status_code == 501
        assert response.json()["detail"] == "Not implemented yet"

    def test_get_pet_not_implemented(self, client: TestClient) -> None:
        """Get pet endpoint should return 501 until implemented."""
        response = client.get("/api/v1/pets/owner/repo")
        assert response.status_code == 501
        assert response.json()["detail"] == "Not implemented yet"

    def test_feed_pet_not_implemented(self, client: TestClient) -> None:
        """Feed pet endpoint should return 501 until implemented."""
        response = client.post("/api/v1/pets/owner/repo/feed")
        assert response.status_code == 501
        assert response.json()["detail"] == "Not implemented yet"

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


class TestQueueStatsEndpoint:
    """Tests for the queue stats endpoint."""

    def test_queue_stats_returns_200(self, client: TestClient) -> None:
        """Queue stats endpoint should return 200 OK."""
        response = client.get("/api/v1/admin/queue/stats")
        assert response.status_code == 200

    def test_queue_stats_returns_expected_fields(self, client: TestClient) -> None:
        """Queue stats endpoint should return all expected fields."""
        response = client.get("/api/v1/admin/queue/stats")
        data = response.json()
        assert "pending" in data
        assert "processing" in data
        assert "completed" in data
        assert "failed" in data

    def test_queue_stats_returns_zero_for_empty_queue(self, client: TestClient) -> None:
        """Queue stats should return zeros when no jobs exist."""
        response = client.get("/api/v1/admin/queue/stats")
        data = response.json()
        assert data["pending"] == 0
        assert data["processing"] == 0
        assert data["completed"] == 0
        assert data["failed"] == 0
