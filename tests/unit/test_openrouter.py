"""Tests for the OpenRouter image generation service."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from github_tamagotchi.services.openrouter import OpenRouterService


def _make_openrouter_response(image_b64: str) -> dict:
    """Build a mock OpenRouter API response with an image."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Here is your image",
                    "images": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_b64}"
                            },
                        }
                    ],
                }
            }
        ]
    }


def _make_openrouter_response_no_images() -> dict:
    """Build a mock OpenRouter API response without images."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "I cannot generate images",
                    "images": [],
                }
            }
        ]
    }


class TestOpenRouterService:
    """Tests for the OpenRouterService class."""

    @pytest.fixture
    def service(self) -> OpenRouterService:
        """Create a test service instance."""
        return OpenRouterService(
            api_key="test-api-key",
            model="google/gemini-2.5-flash-image",
            timeout=10.0,
        )

    @pytest.mark.asyncio
    async def test_generate_success(self, service: OpenRouterService) -> None:
        """Should return success result with image data."""
        fake_png = b"\x89PNG\r\n\x1a\n"
        fake_b64 = base64.b64encode(fake_png).decode()
        response_data = _make_openrouter_response(fake_b64)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await service.generate_pet_image("owner", "repo", "adult")

        assert result.success is True
        assert result.image_data == fake_png
        assert result.filename == "owner_repo_adult.png"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_generate_no_images_in_response(
        self, service: OpenRouterService
    ) -> None:
        """Should return error when response has no images."""
        response_data = _make_openrouter_response_no_images()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await service.generate_pet_image("owner", "repo", "baby")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_generate_empty_choices(
        self, service: OpenRouterService
    ) -> None:
        """Should return error when response has no choices."""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await service.generate_pet_image("owner", "repo", "egg")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_generate_timeout(self, service: OpenRouterService) -> None:
        """Should handle timeout errors gracefully."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )
            result = await service.generate_pet_image("owner", "repo", "teen")

        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_generate_http_error(
        self, service: OpenRouterService
    ) -> None:
        """Should handle HTTP errors gracefully."""
        mock_response = httpx.Response(
            429,
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        )
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Rate limited",
                    request=mock_response.request,
                    response=mock_response,
                )
            )
            result = await service.generate_pet_image("owner", "repo", "elder")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_check_health_success(
        self, service: OpenRouterService
    ) -> None:
        """Should return True when OpenRouter is reachable."""
        mock_response = AsyncMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )
            result = await service.check_health()

        assert result is True

    @pytest.mark.asyncio
    async def test_check_health_failure(
        self, service: OpenRouterService
    ) -> None:
        """Should return False when OpenRouter is unreachable."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            result = await service.check_health()

        assert result is False

    @pytest.mark.asyncio
    async def test_check_health_no_api_key(self) -> None:
        """Should return False when no API key is configured."""
        service = OpenRouterService(api_key=None)
        result = await service.check_health()
        assert result is False

    @pytest.mark.asyncio
    async def test_generate_no_api_key(self) -> None:
        """Should return error when API key is not configured."""
        service = OpenRouterService(api_key=None)
        result = await service.generate_pet_image("owner", "repo", "adult")

        assert result.success is False
        assert "API key not configured" in result.error

    @pytest.mark.asyncio
    async def test_prompt_includes_appearance(
        self, service: OpenRouterService
    ) -> None:
        """Should include pet appearance details in the API call."""
        fake_png = b"\x89PNG\r\n\x1a\n"
        fake_b64 = base64.b64encode(fake_png).decode()
        response_data = _make_openrouter_response(fake_b64)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_data

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post
            await service.generate_pet_image("octocat", "hello-world", "adult")

            # Verify the prompt was sent
            call_args = mock_post.call_args
            payload = call_args.kwargs["json"]
            assert payload["model"] == "google/gemini-2.5-flash-image"
            assert payload["modalities"] == ["image", "text"]
            assert len(payload["messages"]) == 1
            # The message content should reference the pet appearance
            content = payload["messages"][0]["content"]
            assert "pixel art" in content.lower()


class TestExtractImage:
    """Tests for image extraction from API response."""

    def test_extract_valid_base64(self) -> None:
        """Should extract and decode base64 image data."""
        service = OpenRouterService(api_key="test")
        fake_png = b"\x89PNG\r\n\x1a\n"
        fake_b64 = base64.b64encode(fake_png).decode()
        data = _make_openrouter_response(fake_b64)

        result = service._extract_image(data)
        assert result == fake_png

    def test_extract_no_choices(self) -> None:
        """Should return None for empty choices."""
        service = OpenRouterService(api_key="test")
        result = service._extract_image({"choices": []})
        assert result is None

    def test_extract_no_images(self) -> None:
        """Should return None when no images in response."""
        service = OpenRouterService(api_key="test")
        data = _make_openrouter_response_no_images()
        result = service._extract_image(data)
        assert result is None

    def test_extract_invalid_data_uri(self) -> None:
        """Should return None for non-data URI."""
        service = OpenRouterService(api_key="test")
        data = {
            "choices": [
                {
                    "message": {
                        "images": [
                            {
                                "image_url": {
                                    "url": "https://example.com/image.png"
                                }
                            }
                        ]
                    }
                }
            ]
        }
        result = service._extract_image(data)
        assert result is None
