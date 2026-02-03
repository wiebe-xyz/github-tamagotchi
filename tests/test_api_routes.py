"""Tests for API routes."""

import pytest
from httpx import AsyncClient

from github_tamagotchi import __version__


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, async_client: AsyncClient) -> None:
        """Health endpoint should return 200 OK."""
        response = await async_client.get("/api/v1/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_healthy_status(self, async_client: AsyncClient) -> None:
        """Health endpoint should return healthy status."""
        response = await async_client.get("/api/v1/health")
        data = response.json()
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_returns_version(self, async_client: AsyncClient) -> None:
        """Health endpoint should return current version."""
        response = await async_client.get("/api/v1/health")
        data = response.json()
        assert data["version"] == __version__


class TestCreatePetEndpoint:
    """Tests for the create pet endpoint."""

    @pytest.mark.asyncio
    async def test_create_pet_success(self, async_client: AsyncClient) -> None:
        """Create pet should return 201 with pet data."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "TestPet"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["repo_owner"] == "owner"
        assert data["repo_name"] == "repo"
        assert data["name"] == "TestPet"
        assert data["stage"] == "egg"
        assert data["mood"] == "content"
        assert data["health"] == 100
        assert data["experience"] == 0
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_pet_duplicate_returns_409(self, async_client: AsyncClient) -> None:
        """Create pet should return 409 for duplicate repo."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "dup-owner", "repo_name": "dup-repo", "name": "Pet1"},
        )
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "dup-owner", "repo_name": "dup-repo", "name": "Pet2"},
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_pet_validates_empty_body(self, async_client: AsyncClient) -> None:
        """Create pet should return 422 for empty body."""
        response = await async_client.post("/api/v1/pets", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_pet_validates_missing_name(self, async_client: AsyncClient) -> None:
        """Create pet should return 422 for missing name."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_pet_validates_empty_name(self, async_client: AsyncClient) -> None:
        """Create pet should return 422 for empty name."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": ""},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_pet_validates_name_too_long(self, async_client: AsyncClient) -> None:
        """Create pet should return 422 for name exceeding 100 chars."""
        response = await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "x" * 101},
        )
        assert response.status_code == 422


class TestGetPetEndpoint:
    """Tests for the get pet endpoint."""

    @pytest.mark.asyncio
    async def test_get_pet_success(self, async_client: AsyncClient) -> None:
        """Get pet should return 200 with pet data."""
        # First create a pet
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "get-owner", "repo_name": "get-repo", "name": "GetPet"},
        )
        # Then fetch it
        response = await async_client.get("/api/v1/pets/get-owner/get-repo")
        assert response.status_code == 200
        data = response.json()
        assert data["repo_owner"] == "get-owner"
        assert data["repo_name"] == "get-repo"
        assert data["name"] == "GetPet"

    @pytest.mark.asyncio
    async def test_get_pet_not_found(self, async_client: AsyncClient) -> None:
        """Get pet should return 404 for non-existent pet."""
        response = await async_client.get("/api/v1/pets/nonexistent/repo")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestListPetsEndpoint:
    """Tests for the list pets endpoint."""

    @pytest.mark.asyncio
    async def test_list_pets_empty(self, async_client: AsyncClient) -> None:
        """List pets should return empty list when no pets exist."""
        response = await async_client.get("/api/v1/pets")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["pages"] == 0

    @pytest.mark.asyncio
    async def test_list_pets_with_data(self, async_client: AsyncClient) -> None:
        """List pets should return all pets."""
        # Create some pets
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "list-owner1", "repo_name": "repo1", "name": "Pet1"},
        )
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "list-owner2", "repo_name": "repo2", "name": "Pet2"},
        )
        response = await async_client.get("/api/v1/pets")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 2
        assert data["pages"] == 1

    @pytest.mark.asyncio
    async def test_list_pets_pagination(self, async_client: AsyncClient) -> None:
        """List pets should support pagination."""
        # Create 3 pets
        for i in range(3):
            await async_client.post(
                "/api/v1/pets",
                json={"repo_owner": f"page-owner{i}", "repo_name": f"repo{i}", "name": f"Pet{i}"},
            )
        # Get first page with page_size=2
        response = await async_client.get("/api/v1/pets?page=1&page_size=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["pages"] == 2

        # Get second page
        response = await async_client.get("/api/v1/pets?page=2&page_size=2")
        data = response.json()
        assert len(data["items"]) == 1
        assert data["page"] == 2

    @pytest.mark.asyncio
    async def test_list_pets_invalid_page(self, async_client: AsyncClient) -> None:
        """List pets should return 422 for invalid page number."""
        response = await async_client.get("/api/v1/pets?page=0")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_pets_page_size_limits(self, async_client: AsyncClient) -> None:
        """List pets should enforce page_size limits."""
        response = await async_client.get("/api/v1/pets?page_size=101")
        assert response.status_code == 422


class TestFeedPetEndpoint:
    """Tests for the feed pet endpoint."""

    @pytest.mark.asyncio
    async def test_feed_pet_success(self, async_client: AsyncClient) -> None:
        """Feed pet should return 200 with updated pet data."""
        # First create a pet
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "feed-owner", "repo_name": "feed-repo", "name": "FeedPet"},
        )
        # Then feed it
        response = await async_client.post("/api/v1/pets/feed-owner/feed-repo/feed")
        assert response.status_code == 200
        data = response.json()
        assert data["repo_owner"] == "feed-owner"
        assert data["repo_name"] == "feed-repo"

    @pytest.mark.asyncio
    async def test_feed_pet_not_found(self, async_client: AsyncClient) -> None:
        """Feed pet should return 404 for non-existent pet."""
        response = await async_client.post("/api/v1/pets/nonexistent/repo/feed")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_feed_pet_improves_health(self, async_client: AsyncClient) -> None:
        """Feed pet should improve health by 10."""
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "health-owner", "repo_name": "health-repo", "name": "HealthPet"},
        )
        # Pet starts with 100 health, feeding should not exceed 100
        response = await async_client.post("/api/v1/pets/health-owner/health-repo/feed")
        data = response.json()
        assert data["health"] == 100  # Already at max


class TestDeletePetEndpoint:
    """Tests for the delete pet endpoint."""

    @pytest.mark.asyncio
    async def test_delete_pet_success(self, async_client: AsyncClient) -> None:
        """Delete pet should return 204 and remove pet."""
        # First create a pet
        await async_client.post(
            "/api/v1/pets",
            json={"repo_owner": "delete-owner", "repo_name": "delete-repo", "name": "DeletePet"},
        )
        # Delete it
        response = await async_client.delete("/api/v1/pets/delete-owner/delete-repo")
        assert response.status_code == 204

        # Verify it's gone
        response = await async_client.get("/api/v1/pets/delete-owner/delete-repo")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_pet_not_found(self, async_client: AsyncClient) -> None:
        """Delete pet should return 404 for non-existent pet."""
        response = await async_client.delete("/api/v1/pets/nonexistent/repo")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]
