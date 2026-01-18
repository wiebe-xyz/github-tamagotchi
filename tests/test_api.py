"""Tests for API routes with database integration."""

from httpx import AsyncClient

from github_tamagotchi import __version__


async def test_root_endpoint(async_client: AsyncClient) -> None:
    """Test root endpoint returns app info."""
    response = await async_client.get("/")
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "GitHub Tamagotchi"
    assert data["version"] == __version__
    assert data["docs"] == "/docs"


async def test_health_check_returns_database_status(async_client: AsyncClient) -> None:
    """Test health check includes database connectivity status."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == __version__
    assert data["database"] == "connected"


async def test_health_check_response_schema(async_client: AsyncClient) -> None:
    """Test health check response matches expected schema."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert "version" in data
    assert "database" in data


# === Create Pet Tests ===


async def test_create_pet_success(async_client: AsyncClient) -> None:
    """Test creating a new pet returns 201 with pet data."""
    response = await async_client.post(
        "/api/v1/pets",
        json={
            "repo_owner": "test-owner",
            "repo_name": "test-repo",
            "name": "TestPet",
        },
    )
    assert response.status_code == 201

    data = response.json()
    assert data["repo_owner"] == "test-owner"
    assert data["repo_name"] == "test-repo"
    assert data["name"] == "TestPet"
    assert data["stage"] == "egg"
    assert data["mood"] == "content"
    assert data["health"] == 100
    assert data["experience"] == 0
    assert "id" in data


async def test_create_pet_duplicate_returns_409(async_client: AsyncClient) -> None:
    """Test creating a duplicate pet returns 409 conflict."""
    # Create first pet
    await async_client.post(
        "/api/v1/pets",
        json={
            "repo_owner": "dup-owner",
            "repo_name": "dup-repo",
            "name": "FirstPet",
        },
    )

    # Try to create duplicate
    response = await async_client.post(
        "/api/v1/pets",
        json={
            "repo_owner": "dup-owner",
            "repo_name": "dup-repo",
            "name": "SecondPet",
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


async def test_create_pet_validates_request_body(async_client: AsyncClient) -> None:
    """Test create pet validates required fields."""
    response = await async_client.post(
        "/api/v1/pets",
        json={"repo_owner": "test-owner"},  # Missing required fields
    )
    assert response.status_code == 422  # Validation error


async def test_create_pet_validates_empty_name(async_client: AsyncClient) -> None:
    """Test create pet rejects empty name."""
    response = await async_client.post(
        "/api/v1/pets",
        json={
            "repo_owner": "test-owner",
            "repo_name": "test-repo",
            "name": "",
        },
    )
    assert response.status_code == 422


# === Get Pet Tests ===


async def test_get_pet_success(async_client: AsyncClient) -> None:
    """Test getting an existing pet returns 200 with pet data."""
    # Create a pet first
    await async_client.post(
        "/api/v1/pets",
        json={
            "repo_owner": "get-owner",
            "repo_name": "get-repo",
            "name": "GetPet",
        },
    )

    # Get the pet
    response = await async_client.get("/api/v1/pets/get-owner/get-repo")
    assert response.status_code == 200

    data = response.json()
    assert data["repo_owner"] == "get-owner"
    assert data["repo_name"] == "get-repo"
    assert data["name"] == "GetPet"


async def test_get_pet_not_found(async_client: AsyncClient) -> None:
    """Test getting a non-existent pet returns 404."""
    response = await async_client.get("/api/v1/pets/nonexistent-owner/nonexistent-repo")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# === List Pets Tests ===


async def test_list_pets_empty(async_client: AsyncClient) -> None:
    """Test listing pets when none exist returns empty list."""
    response = await async_client.get("/api/v1/pets")
    assert response.status_code == 200

    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["pages"] == 1


async def test_list_pets_with_pagination(async_client: AsyncClient) -> None:
    """Test listing pets with pagination."""
    # Create 3 pets
    for i in range(3):
        await async_client.post(
            "/api/v1/pets",
            json={
                "repo_owner": f"owner-{i}",
                "repo_name": f"repo-{i}",
                "name": f"Pet{i}",
            },
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
    assert response.status_code == 200

    data = response.json()
    assert len(data["items"]) == 1
    assert data["page"] == 2


async def test_list_pets_invalid_page(async_client: AsyncClient) -> None:
    """Test listing pets with invalid page parameter returns 422."""
    response = await async_client.get("/api/v1/pets?page=0")
    assert response.status_code == 422


async def test_list_pets_invalid_page_size(async_client: AsyncClient) -> None:
    """Test listing pets with invalid page_size parameter returns 422."""
    response = await async_client.get("/api/v1/pets?page_size=101")
    assert response.status_code == 422


# === Feed Pet Tests ===


async def test_feed_pet_success(async_client: AsyncClient) -> None:
    """Test feeding a pet increases health and sets mood to happy."""
    # Create a pet first
    create_response = await async_client.post(
        "/api/v1/pets",
        json={
            "repo_owner": "feed-owner",
            "repo_name": "feed-repo",
            "name": "FeedPet",
        },
    )
    initial_health = create_response.json()["health"]

    # Feed the pet
    response = await async_client.post("/api/v1/pets/feed-owner/feed-repo/feed")
    assert response.status_code == 200

    data = response.json()
    assert data["mood"] == "happy"
    # Health should be at max since we started at 100
    assert data["health"] == min(100, initial_health + 10)


async def test_feed_pet_not_found(async_client: AsyncClient) -> None:
    """Test feeding a non-existent pet returns 404."""
    response = await async_client.post("/api/v1/pets/nonexistent-owner/nonexistent-repo/feed")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


# === Delete Pet Tests ===


async def test_delete_pet_success(async_client: AsyncClient) -> None:
    """Test deleting a pet returns 204 and removes the pet."""
    # Create a pet first
    await async_client.post(
        "/api/v1/pets",
        json={
            "repo_owner": "del-owner",
            "repo_name": "del-repo",
            "name": "DelPet",
        },
    )

    # Delete the pet
    response = await async_client.delete("/api/v1/pets/del-owner/del-repo")
    assert response.status_code == 204

    # Verify pet is gone
    get_response = await async_client.get("/api/v1/pets/del-owner/del-repo")
    assert get_response.status_code == 404


async def test_delete_pet_not_found(async_client: AsyncClient) -> None:
    """Test deleting a non-existent pet returns 404."""
    response = await async_client.delete("/api/v1/pets/nonexistent-owner/nonexistent-repo")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]
