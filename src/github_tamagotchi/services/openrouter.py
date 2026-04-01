"""OpenRouter image generation service for pet sprites."""

import base64
import binascii
from typing import Any

import httpx
import structlog

from github_tamagotchi.core.config import settings
from github_tamagotchi.services.image_generation import (
    NEGATIVE_PROMPT,
    GenerationResult,
    build_prompt,
    get_pet_appearance,
)

logger = structlog.get_logger()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterService:
    """Service for generating pet images via OpenRouter API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.openrouter_api_key
        self.model = model if model is not None else settings.openrouter_model
        self.timeout = timeout if timeout is not None else settings.openrouter_timeout

    async def generate_pet_image(
        self, owner: str, repo: str, stage: str
    ) -> GenerationResult:
        """Generate a pet image using OpenRouter's image generation API."""
        if not self.api_key:
            return GenerationResult(
                success=False, error="OpenRouter API key not configured"
            )

        try:
            appearance = get_pet_appearance(owner, repo)
            prompt = build_prompt(appearance, stage)

            image_data = await self._call_api(prompt)

            if image_data:
                return GenerationResult(
                    success=True,
                    image_data=image_data,
                    filename=f"{owner}_{repo}_{stage}.png",
                )
            return GenerationResult(
                success=False,
                error="No image data in OpenRouter response",
            )

        except httpx.TimeoutException:
            logger.error(
                "OpenRouter request timed out",
                owner=owner,
                repo=repo,
                stage=stage,
            )
            return GenerationResult(
                success=False, error="Image generation timed out"
            )
        except Exception as e:
            logger.error(
                "OpenRouter image generation failed",
                owner=owner,
                repo=repo,
                stage=stage,
                error=str(e),
            )
            return GenerationResult(success=False, error=str(e))

    async def _call_api(self, prompt: str) -> bytes | None:
        """Call the OpenRouter API and return image bytes."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "modalities": ["image", "text"],
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Generate a pixel art image based on this description. "
                        f"Do not include any text in the image. "
                        f"Description: {prompt} "
                        f"Avoid: {NEGATIVE_PROMPT}"
                    ),
                }
            ],
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        return self._extract_image(data)

    def _extract_image(self, data: dict[str, Any]) -> bytes | None:
        """Extract image bytes from OpenRouter response."""
        choices = data.get("choices", [])
        if not choices:
            return None

        message = choices[0].get("message", {})
        images = message.get("images", [])

        if not images:
            return None

        image_url = images[0].get("image_url", {}).get("url", "")

        if not image_url.startswith("data:"):
            return None

        # Parse data URI: data:image/png;base64,<data>
        try:
            _, encoded = image_url.split(",", 1)
            return base64.b64decode(encoded)
        except (ValueError, binascii.Error):
            logger.error("Failed to decode base64 image data")
            return None

    async def check_health(self) -> bool:
        """Check if OpenRouter API is reachable."""
        if not self.api_key:
            return False

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return response.status_code == 200
        except Exception:
            return False
