"""Tests for API routes."""

from unittest.mock import AsyncMock, patch

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


class TestCharacteristicsEndpoint:
    """Tests for the pet characteristics endpoint."""

    def test_get_characteristics_returns_200(self, client: TestClient) -> None:
        """Characteristics endpoint should return 200 OK."""
        response = client.get("/api/v1/pets/owner/repo/characteristics")
        assert response.status_code == 200

    def test_get_characteristics_has_required_fields(self, client: TestClient) -> None:
        """Characteristics should have color, pattern, and species."""
        response = client.get("/api/v1/pets/owner/repo/characteristics")
        data = response.json()
        assert "color" in data
        assert "pattern" in data
        assert "species" in data

    def test_get_characteristics_deterministic(self, client: TestClient) -> None:
        """Same repo should always get same characteristics."""
        response1 = client.get("/api/v1/pets/testowner/testrepo/characteristics")
        response2 = client.get("/api/v1/pets/testowner/testrepo/characteristics")
        assert response1.json() == response2.json()

    def test_get_characteristics_different_per_repo(self, client: TestClient) -> None:
        """Different repos should get different characteristics."""
        response1 = client.get("/api/v1/pets/owner1/repo1/characteristics")
        response2 = client.get("/api/v1/pets/owner2/repo2/characteristics")
        # Very unlikely to be the same for different repos
        data1 = response1.json()
        data2 = response2.json()
        assert not (
            data1["color"] == data2["color"]
            and data1["pattern"] == data2["pattern"]
            and data1["species"] == data2["species"]
        )


class TestImageEndpoints:
    """Tests for image generation endpoints."""

    def test_get_image_invalid_stage_returns_400(self, client: TestClient) -> None:
        """Invalid stage should return 400."""
        response = client.get("/api/v1/pets/owner/repo/image/invalid")
        assert response.status_code == 400
        assert "Invalid stage" in response.json()["detail"]

    def test_get_image_no_storage_returns_503(self, client: TestClient) -> None:
        """Missing storage config should return 503."""
        with patch("github_tamagotchi.api.routes.settings") as mock_settings:
            mock_settings.minio_endpoint = None
            response = client.get("/api/v1/pets/owner/repo/image/egg")
            assert response.status_code == 503
            assert "storage not configured" in response.json()["detail"]

    def test_get_image_returns_cached_image(self, client: TestClient) -> None:
        """Should return cached image if available."""
        mock_storage = AsyncMock()
        mock_storage.get_image.return_value = b"fake image data"

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch("github_tamagotchi.api.routes.StorageService") as mock_storage_cls,
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_storage_cls.return_value = mock_storage

            response = client.get("/api/v1/pets/owner/repo/image/egg")

            assert response.status_code == 200
            assert response.content == b"fake image data"
            assert response.headers["content-type"] == "image/png"

    def test_get_image_no_image_no_comfyui_returns_404(self, client: TestClient) -> None:
        """Should return 404 when no image and ComfyUI not configured."""
        mock_storage = AsyncMock()
        mock_storage.get_image.return_value = None

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch("github_tamagotchi.api.routes.StorageService") as mock_storage_cls,
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = True
            mock_settings.comfyui_url = None
            mock_storage_cls.return_value = mock_storage

            response = client.get("/api/v1/pets/owner/repo/image/baby")

            assert response.status_code == 404
            assert "generation not available" in response.json()["detail"]

    def test_generate_images_disabled_returns_503(self, client: TestClient) -> None:
        """Should return 503 when generation is disabled."""
        with patch("github_tamagotchi.api.routes.settings") as mock_settings:
            mock_settings.image_generation_enabled = False

            response = client.post("/api/v1/pets/owner/repo/generate-images")

            assert response.status_code == 503
            assert "disabled" in response.json()["detail"]

    def test_generate_images_no_comfyui_returns_503(self, client: TestClient) -> None:
        """Should return 503 when ComfyUI not configured."""
        with patch("github_tamagotchi.api.routes.settings") as mock_settings:
            mock_settings.image_generation_enabled = True
            mock_settings.comfyui_url = None

            response = client.post("/api/v1/pets/owner/repo/generate-images")

            assert response.status_code == 503
            assert "ComfyUI not configured" in response.json()["detail"]

    def test_generate_images_no_storage_returns_503(self, client: TestClient) -> None:
        """Should return 503 when storage not configured."""
        with patch("github_tamagotchi.api.routes.settings") as mock_settings:
            mock_settings.image_generation_enabled = True
            mock_settings.comfyui_url = "http://localhost:8188"
            mock_settings.minio_endpoint = None

            response = client.post("/api/v1/pets/owner/repo/generate-images")

            assert response.status_code == 503
            assert "storage not configured" in response.json()["detail"]

    def test_regenerate_images_disabled_returns_503(self, client: TestClient) -> None:
        """Should return 503 when generation is disabled."""
        with patch("github_tamagotchi.api.routes.settings") as mock_settings:
            mock_settings.image_generation_enabled = False

            response = client.post("/api/v1/pets/owner/repo/regenerate-images")

            assert response.status_code == 503
            assert "disabled" in response.json()["detail"]
