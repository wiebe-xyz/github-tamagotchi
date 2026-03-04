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


async def test_create_pet_validates_request_body(async_client: AsyncClient) -> None:
    """Test create pet validates required fields."""
    response = await async_client.post(
        "/api/v1/pets",
        json={"repo_owner": "test-owner"},  # Missing required fields
    )
    assert response.status_code == 422  # Validation error
