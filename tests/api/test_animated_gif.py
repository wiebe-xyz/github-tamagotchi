"""Tests for the animated GIF endpoint."""

import io
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from PIL import Image

from github_tamagotchi.services.sprite_sheet import SpriteSheetResult


def _make_gif() -> bytes:
    """Create a minimal valid animated GIF for testing."""
    img = Image.new("P", (8, 8), color=0)
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


def _make_frame_bytes() -> bytes:
    """Create a minimal RGBA PNG frame."""
    img = Image.new("RGBA", (8, 8), color=(100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_sprite_sheet_result(success: bool = True) -> SpriteSheetResult:
    """Build a mock SpriteSheetResult with minimal valid frame data."""
    if not success:
        return SpriteSheetResult(success=False, error="generation failed")

    frame = _make_frame_bytes()
    return SpriteSheetResult(
        success=True,
        sprite_sheet_data=frame,
        frames=[frame] * 6,
        canonical_appearance="a sky blue round blob creature with small antenna",
    )


def _mock_storage(gif_data: bytes | None = None, raise_on_get: bool = False) -> MagicMock:
    """Build a MagicMock StorageService with preconfigured async methods."""
    mock = MagicMock()
    if raise_on_get:
        mock.get_animated_gif = AsyncMock(side_effect=Exception("storage down"))
    else:
        mock.get_animated_gif = AsyncMock(return_value=gif_data)
    mock.upload_sprite_sheet = AsyncMock(return_value="path")
    mock.upload_frame = AsyncMock(return_value="path")
    mock.upload_animated_gif = AsyncMock(return_value="path")
    return mock


class TestGetPetAnimatedGif:
    """Tests for GET /api/v1/pets/{owner}/{repo}/image/{stage}/animated."""

    BASE_URL = "/api/v1/pets/testowner/testrepo/image/adult/animated"

    async def test_invalid_stage_returns_400(self, async_client: AsyncClient) -> None:
        """An unknown stage name should return 400."""
        mock_storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = False
            mock_settings.image_generation_provider = "openrouter"
            response = await async_client.get(
                "/api/v1/pets/owner/repo/image/invalid_stage/animated"
            )
        assert response.status_code == 400

    async def test_no_minio_returns_503(self, async_client: AsyncClient) -> None:
        """If MinIO is not configured, return 503."""
        with patch("github_tamagotchi.api.routes.settings") as mock_settings:
            mock_settings.minio_endpoint = None
            response = await async_client.get(self.BASE_URL)
        assert response.status_code == 503

    async def test_returns_cached_gif_when_exists(self, async_client: AsyncClient) -> None:
        """If an animated GIF already exists in storage, return it directly."""
        gif_data = _make_gif()
        mock_storage = _mock_storage(gif_data=gif_data)

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = True
            mock_settings.image_generation_provider = "openrouter"
            response = await async_client.get(self.BASE_URL)

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/gif"
        assert response.content == gif_data

    async def test_generation_disabled_returns_404(self, async_client: AsyncClient) -> None:
        """If generation is disabled and no GIF exists, return 404."""
        mock_storage = _mock_storage(gif_data=None)

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = False
            mock_settings.image_generation_provider = "openrouter"
            response = await async_client.get(self.BASE_URL)

        assert response.status_code == 404

    async def test_comfyui_provider_returns_404(self, async_client: AsyncClient) -> None:
        """Sprite sheet generation is not supported for the ComfyUI provider."""
        mock_storage = _mock_storage(gif_data=None)

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = True
            mock_settings.image_generation_provider = "comfyui"
            response = await async_client.get(self.BASE_URL)

        assert response.status_code == 404

    async def test_successful_generation_returns_gif(self, async_client: AsyncClient) -> None:
        """When no GIF exists, generate sprite sheet and return animated GIF."""
        mock_storage = _mock_storage(gif_data=None)
        sheet_result = _make_sprite_sheet_result(success=True)

        mock_openrouter = MagicMock()
        mock_openrouter.generate_sprite_sheet = AsyncMock(return_value=sheet_result)

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
            patch(
                "github_tamagotchi.api.routes.OpenRouterService",
                return_value=mock_openrouter,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = True
            mock_settings.image_generation_provider = "openrouter"
            response = await async_client.get(self.BASE_URL)

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/gif"

    async def test_generation_failure_returns_503(self, async_client: AsyncClient) -> None:
        """When sprite sheet generation fails, return 503."""
        mock_storage = _mock_storage(gif_data=None)
        sheet_result = _make_sprite_sheet_result(success=False)

        mock_openrouter = MagicMock()
        mock_openrouter.generate_sprite_sheet = AsyncMock(return_value=sheet_result)

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
            patch(
                "github_tamagotchi.api.routes.OpenRouterService",
                return_value=mock_openrouter,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = True
            mock_settings.image_generation_provider = "openrouter"
            response = await async_client.get(self.BASE_URL)

        assert response.status_code == 503

    async def test_storage_error_returns_503(self, async_client: AsyncClient) -> None:
        """If storage raises an exception, return 503."""
        mock_storage = _mock_storage(raise_on_get=True)

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = True
            mock_settings.image_generation_provider = "openrouter"
            response = await async_client.get(self.BASE_URL)

        assert response.status_code == 503

    async def test_cache_control_header_present(self, async_client: AsyncClient) -> None:
        """Response should include appropriate Cache-Control header."""
        gif_data = _make_gif()
        mock_storage = _mock_storage(gif_data=gif_data)

        with (
            patch("github_tamagotchi.api.routes.settings") as mock_settings,
            patch(
                "github_tamagotchi.api.routes.StorageService",
                return_value=mock_storage,
            ),
        ):
            mock_settings.minio_endpoint = "localhost:9000"
            mock_settings.image_generation_enabled = True
            mock_settings.image_generation_provider = "openrouter"
            response = await async_client.get(self.BASE_URL)

        assert response.status_code == 200
        assert "cache-control" in response.headers
        assert "max-age" in response.headers["cache-control"]
