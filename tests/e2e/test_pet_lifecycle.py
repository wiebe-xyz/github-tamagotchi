"""E2E tests for the complete pet lifecycle."""

from httpx import AsyncClient


class TestPetLifecycle:
    """Test the full pet lifecycle: create -> get -> feed -> list -> delete."""

    async def test_full_pet_lifecycle(self, e2e_client: AsyncClient) -> None:
        """A user creates a pet, interacts with it, and eventually deletes it."""
        # Step 1: Create a pet
        create_resp = await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "octocat", "repo_name": "hello-world", "name": "Octo"},
        )
        assert create_resp.status_code == 201
        pet = create_resp.json()
        assert pet["name"] == "Octo"
        assert pet["stage"] == "egg"
        assert pet["health"] == 100
        assert pet["mood"] == "content"

        # Step 2: Retrieve the pet
        get_resp = await e2e_client.get("/api/v1/pets/octocat/hello-world")
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "Octo"

        # Step 3: Feed the pet
        feed_resp = await e2e_client.post("/api/v1/pets/octocat/hello-world/feed")
        assert feed_resp.status_code == 200
        feed_data = feed_resp.json()
        assert "has been fed" in feed_data["message"]
        assert feed_data["pet"]["last_fed_at"] is not None

        # Step 4: Verify pet appears in listing
        list_resp = await e2e_client.get("/api/v1/pets")
        assert list_resp.status_code == 200
        listing = list_resp.json()
        assert listing["total"] == 1
        assert listing["items"][0]["name"] == "Octo"

        # Step 5: Delete the pet
        delete_resp = await e2e_client.delete("/api/v1/pets/octocat/hello-world")
        assert delete_resp.status_code == 204

        # Step 6: Confirm deletion
        get_resp = await e2e_client.get("/api/v1/pets/octocat/hello-world")
        assert get_resp.status_code == 404

    async def test_duplicate_pet_prevention(self, e2e_client: AsyncClient) -> None:
        """Creating two pets for the same repo should fail."""
        await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "First"},
        )

        dup_resp = await e2e_client.post(
            "/api/v1/pets",
            json={"repo_owner": "owner", "repo_name": "repo", "name": "Second"},
        )
        assert dup_resp.status_code == 409


class TestHealthEndpointE2E:
    """E2E tests for the health check endpoint."""

    async def test_health_check(self, e2e_client: AsyncClient) -> None:
        """Health endpoint returns status with database connectivity."""
        resp = await e2e_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"
        assert "version" in data


class TestPaginationE2E:
    """E2E tests for pagination across multiple pets."""

    async def test_pagination_across_pages(self, e2e_client: AsyncClient) -> None:
        """Create many pets and verify pagination works end-to-end."""
        for i in range(12):
            resp = await e2e_client.post(
                "/api/v1/pets",
                json={"repo_owner": "org", "repo_name": f"repo-{i}", "name": f"Pet{i}"},
            )
            assert resp.status_code == 201

        # Page 1
        page1 = await e2e_client.get("/api/v1/pets?page=1&per_page=5")
        data1 = page1.json()
        assert len(data1["items"]) == 5
        assert data1["total"] == 12
        assert data1["pages"] == 3

        # Page 3 (last page, partial)
        page3 = await e2e_client.get("/api/v1/pets?page=3&per_page=5")
        data3 = page3.json()
        assert len(data3["items"]) == 2


class TestErrorHandlingE2E:
    """E2E tests for error scenarios."""

    async def test_get_nonexistent_pet(self, e2e_client: AsyncClient) -> None:
        """Getting a pet that doesn't exist returns 404."""
        resp = await e2e_client.get("/api/v1/pets/nobody/nothing")
        assert resp.status_code == 404

    async def test_feed_nonexistent_pet(self, e2e_client: AsyncClient) -> None:
        """Feeding a pet that doesn't exist returns 404."""
        resp = await e2e_client.post("/api/v1/pets/nobody/nothing/feed")
        assert resp.status_code == 404

    async def test_delete_nonexistent_pet(self, e2e_client: AsyncClient) -> None:
        """Deleting a pet that doesn't exist returns 404."""
        resp = await e2e_client.delete("/api/v1/pets/nobody/nothing")
        assert resp.status_code == 404

    async def test_invalid_create_payload(self, e2e_client: AsyncClient) -> None:
        """Creating a pet with invalid data returns 422."""
        resp = await e2e_client.post("/api/v1/pets", json={"repo_owner": ""})
        assert resp.status_code == 422
