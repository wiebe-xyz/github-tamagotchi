"""Tests for image generation provider abstraction."""

from unittest.mock import patch

from github_tamagotchi.services.image_generation import ImageGenerationService
from github_tamagotchi.services.image_queue import get_image_provider
from github_tamagotchi.services.openrouter import OpenRouterService
from github_tamagotchi.services.provider import ImageProvider


class TestImageProvider:
    """Tests for the ImageProvider protocol."""

    def test_openrouter_implements_protocol(self) -> None:
        """OpenRouterService should satisfy the ImageProvider protocol."""
        assert isinstance(OpenRouterService(api_key="test"), ImageProvider)

    def test_comfyui_implements_protocol(self) -> None:
        """ImageGenerationService should satisfy the ImageProvider protocol."""
        assert isinstance(
            ImageGenerationService(comfyui_url="http://test"),
            ImageProvider,
        )


class TestGetImageProvider:
    """Tests for the provider factory function."""

    def test_default_is_openrouter(self) -> None:
        """Default provider should be OpenRouter."""
        with patch(
            "github_tamagotchi.services.image_queue.settings"
        ) as mock_settings:
            mock_settings.image_generation_provider = "openrouter"
            mock_settings.openrouter_api_key = "test-key"
            mock_settings.openrouter_model = "test-model"
            mock_settings.openrouter_timeout = 10.0
            provider = get_image_provider()
        assert isinstance(provider, OpenRouterService)

    def test_comfyui_when_configured(self) -> None:
        """Should return ComfyUI provider when configured."""
        with patch(
            "github_tamagotchi.services.image_queue.settings"
        ) as mock_settings:
            mock_settings.image_generation_provider = "comfyui"
            mock_settings.comfyui_url = "http://comfyui:8188"
            mock_settings.comfyui_timeout = 120.0
            provider = get_image_provider()
        assert isinstance(provider, ImageGenerationService)
