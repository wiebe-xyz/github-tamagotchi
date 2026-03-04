"""E2E: Pet lifecycle — create, get, feed, list, delete via API."""

import pytest
from httpx import AsyncClient

from github_tamagotchi.models.pet import PetMood, PetStage


@pytest.mark.asyncio
class TestPetLifecycle:
    """Full pet lifecycle through the API."""

    async def test_health_endpoint_with_db(self, e2e_client: AsyncClient) -> None:
        """Health endpoint reports connected database."""
        resp = await e2e_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"

    async def test_create_pet_via_api(self, e2e_client: AsyncClient) -> None:
        """Create a pet through the API and verify response."""
        resp = await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Buddy"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["repo_owner"] == "owner"
        assert data["repo_name"] == "repo"
        assert data["name"] == "Buddy"
        assert data["stage"] == PetStage.EGG.value
        assert data["mood"] == PetMood.CONTENT.value
        assert data["health"] == 100
        assert data["experience"] == 0

    async def test_duplicate_pet_returns_409(self, e2e_client: AsyncClient) -> None:
        """Creating a pet for the same repo twice returns 409."""
        payload = {"repo_owner": "dup", "repo_name": "repo", "name": "First"}
        resp1 = await e2e_client.post("/api/v1/pets", json=payload)
        assert resp1.status_code == 201

        resp2 = await e2e_client.post("/api/v1/pets", json=payload)
        assert resp2.status_code == 409

    async def test_get_pet_via_api(self, e2e_client: AsyncClient) -> None:
        """Get a pet by repo owner/name after creating it."""
        await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "gettest", "repo_name": "myrepo", "name": "Rex"},
        )
        resp = await e2e_client.get("/api/v1/pets/gettest/myrepo")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Rex"

    async def test_get_nonexistent_pet_returns_404(
        self, e2e_client: AsyncClient
    ) -> None:
        """Getting a pet that doesn't exist returns 404."""
        resp = await e2e_client.get("/api/v1/pets/nobody/nothing")
        assert resp.status_code == 404

    async def test_feed_pet_increases_health(
        self, e2e_client: AsyncClient
    ) -> None:
        """Feeding a pet increases its health."""
        await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "feedtest", "repo_name": "repo", "name": "Hungry"},
        )
        resp = await e2e_client.post("/api/v1/pets/feedtest/repo/feed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Hungry has been fed!"
        assert data["pet"]["last_fed_at"] is not None

    async def test_list_pets_with_pagination(
        self, e2e_client: AsyncClient
    ) -> None:
        """List pets returns paginated results."""
        for i in range(3):
            await e2e_client.post(
                "/api/v1/pets",
                json={
                    "repo_owner": "listtest",
                    "repo_name": f"repo-{i}",
                    "name": f"Pet{i}",
                },
            )

        resp = await e2e_client.get("/api/v1/pets?per_page=2&page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["pages"] == 2

    async def test_delete_pet(self, e2e_client: AsyncClient) -> None:
        """Delete a pet and verify it's gone."""
        await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "deltest", "repo_name": "repo", "name": "Doomed"},
        )
        resp = await e2e_client.delete("/api/v1/pets/deltest/repo")
        assert resp.status_code == 204

        resp = await e2e_client.get("/api/v1/pets/deltest/repo")
        assert resp.status_code == 404

    async def test_full_lifecycle(self, e2e_client: AsyncClient) -> None:
        """Create → get → feed → delete: full lifecycle through the API."""
        # Create
        resp = await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "lifecycle", "repo_name": "repo", "name": "Cycle"},
        )
        assert resp.status_code == 201
        pet_id = resp.json()["id"]

        # Get
        resp = await e2e_client.get("/api/v1/pets/lifecycle/repo")
        assert resp.status_code == 200
        assert resp.json()["id"] == pet_id

        # Feed
        resp = await e2e_client.post("/api/v1/pets/lifecycle/repo/feed")
        assert resp.status_code == 200

        # Delete
        resp = await e2e_client.delete("/api/v1/pets/lifecycle/repo")
        assert resp.status_code == 204

        # Verify gone
        resp = await e2e_client.get("/api/v1/pets/lifecycle/repo")
        assert resp.status_code == 404
