"""Tests for API routes."""

from fastapi.testclient import TestClient
from httpx import AsyncClient

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


class TestPetsEndpointsAsync:
    """Async tests for pet management endpoints using test database."""

    async def test_create_pet(self, async_client: AsyncClient) -> None:
        """POST /api/v1/pets creates a new pet."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Fluffy"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["repo_owner"] == "testuser"
        assert data["repo_name"] == "testrepo"
        assert data["name"] == "Fluffy"
        assert data["stage"] == "egg"
        assert data["mood"] == "content"
        assert data["health"] == 100
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_pet_duplicate(self, async_client: AsyncClient) -> None:
        """POST /api/v1/pets returns 409 for duplicate."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Fluffy"},
        )

        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "AnotherName"},
        )

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    async def test_create_pet_validation_error(self, async_client: AsyncClient) -> None:
        """POST /api/v1/pets validates input."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "", "repo_name": "testrepo", "name": "Fluffy"},
        )

        assert response.status_code == 422

    async def test_create_pet_validates_missing_fields(self, async_client: AsyncClient) -> None:
        """POST /api/v1/pets should validate required fields."""
        response = await async_client.post("/api/v1/pets", json={})
        assert response.status_code == 422

    async def test_get_pet(self, async_client: AsyncClient) -> None:
        """GET /api/v1/pets/{owner}/{repo} returns a pet."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Fluffy"},
        )

        response = await async_client.get("/api/v1/pets/testuser/testrepo")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Fluffy"

    async def test_get_pet_not_found(self, async_client: AsyncClient) -> None:
        """GET /api/v1/pets/{owner}/{repo} returns 404."""
        response = await async_client.get("/api/v1/pets/nobody/nowhere")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_list_pets_empty(self, async_client: AsyncClient) -> None:
        """GET /api/v1/pets returns empty list."""
        response = await async_client.get("/api/v1/pets")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["pages"] == 1

    async def test_list_pets_pagination(self, async_client: AsyncClient) -> None:
        """GET /api/v1/pets with pagination."""
        for i in range(15):
            await async_client.post(
                "/api/v1/pets",
                json={"repo_owner": "user", "repo_name": f"repo{i}", "name": f"Pet{i}"},
            )

        response = await async_client.get("/api/v1/pets?page=1&per_page=10")
        data = response.json()
        assert len(data["items"]) == 10
        assert data["total"] == 15
        assert data["pages"] == 2

        response = await async_client.get("/api/v1/pets?page=2&per_page=10")
        data = response.json()
        assert len(data["items"]) == 5

    async def test_feed_pet(self, async_client: AsyncClient) -> None:
        """POST /api/v1/pets/{owner}/{repo}/feed feeds a pet."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Fluffy"},
        )

        response = await async_client.post("/api/v1/pets/testuser/testrepo/feed")

        assert response.status_code == 200
        data = response.json()
        assert "has been fed" in data["message"]
        assert data["pet"]["last_fed_at"] is not None

    async def test_feed_pet_not_found(self, async_client: AsyncClient) -> None:
        """POST /api/v1/pets/{owner}/{repo}/feed returns 404."""
        response = await async_client.post("/api/v1/pets/nobody/nowhere/feed")

        assert response.status_code == 404

    async def test_delete_pet(self, async_client: AsyncClient) -> None:
        """DELETE /api/v1/pets/{owner}/{repo} removes a pet."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "testuser", "repo_name": "testrepo", "name": "Fluffy"},
        )

        response = await async_client.delete("/api/v1/pets/testuser/testrepo")

        assert response.status_code == 204

        response = await async_client.get("/api/v1/pets/testuser/testrepo")
        assert response.status_code == 404

    async def test_delete_pet_not_found(self, async_client: AsyncClient) -> None:
        """DELETE /api/v1/pets/{owner}/{repo} returns 404."""
        response = await async_client.delete("/api/v1/pets/nobody/nowhere")

        assert response.status_code == 404
