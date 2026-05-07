"""OpenRouter image generation service for pet sprites."""

import base64
import binascii
from typing import Any

import httpx
import structlog

from github_tamagotchi.core.config import settings
from github_tamagotchi.core.telemetry import get_tracer

from opentelemetry.trace import SpanKind

from github_tamagotchi.services.image_generation import (
    DEFAULT_STYLE,
    NEGATIVE_PROMPT,
    STYLES,
    GenerationResult,
    build_prompt,
    get_pet_appearance,
)
from github_tamagotchi.services.sprite_sheet import (
    SpriteSheetResult,
    analyze_sprite_sheet,
    build_sprite_sheet_prompt,
    extract_frames,
    get_canonical_appearance_description,
    reorder_frames_by_analysis,
)

logger = structlog.get_logger()
_tracer = get_tracer(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _set_genai_response_attributes(span: Any, data: dict[str, Any]) -> None:
    """Set GenAI semantic convention attributes from an OpenRouter response."""
    if resp_id := data.get("id"):
        span.set_attribute("gen_ai.response.id", resp_id)
    if resp_model := data.get("model"):
        span.set_attribute("gen_ai.response.model", resp_model)

    choices = data.get("choices", [])
    if choices:
        reasons = [c.get("finish_reason", "") for c in choices if c.get("finish_reason")]
        if reasons:
            span.set_attribute("gen_ai.response.finish_reasons", reasons)

    usage = data.get("usage", {})
    if usage:
        if (v := usage.get("prompt_tokens")) is not None:
            span.set_attribute("gen_ai.usage.input_tokens", v)
        if (v := usage.get("completion_tokens")) is not None:
            span.set_attribute("gen_ai.usage.output_tokens", v)


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
        self, owner: str, repo: str, stage: str, style: str = DEFAULT_STYLE
    ) -> GenerationResult:
        """Generate a pet image using OpenRouter's image generation API."""
        with _tracer.start_as_current_span(
            "openrouter.generate_pet_image",
            attributes={
                "image.owner": owner,
                "image.repo": repo,
                "image.stage": stage,
                "image.style": style,
                "image.model": self.model,
            },
        ) as span:
            if not self.api_key:
                return GenerationResult(
                    success=False, error="OpenRouter API key not configured"
                )

            try:
                appearance = get_pet_appearance(owner, repo)
                prompt = build_prompt(appearance, stage, style=style)

                style_def = STYLES.get(style, STYLES[DEFAULT_STYLE])
                negative = style_def.get("negative", NEGATIVE_PROMPT)
                image_data = await self._call_api(prompt, negative)

                if image_data:
                    span.set_attribute("image.size_bytes", len(image_data))
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

    async def _call_api(self, prompt: str, negative: str = NEGATIVE_PROMPT) -> bytes | None:
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
                        f"Avoid: {negative}"
                    ),
                }
            ],
        }

        with _tracer.start_as_current_span(
            f"chat {self.model}",
            kind=SpanKind.CLIENT,
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": "openrouter",
                "gen_ai.request.model": self.model,
                "server.address": "openrouter.ai",
                "server.port": 443,
            },
        ) as span:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        OPENROUTER_API_URL,
                        headers=headers,
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()

                _set_genai_response_attributes(span, data)
                return self._extract_image(data)
            except Exception as exc:
                span.set_attribute("error.type", type(exc).__qualname__)
                raise

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

    async def generate_sprite_sheet(
        self,
        owner: str,
        repo: str,
        stage: str,
        style: str = DEFAULT_STYLE,
        canonical_appearance: str | None = None,
    ) -> SpriteSheetResult:
        """Generate a sprite sheet for a pet using a single OpenRouter API call.

        The sprite sheet contains all animation frames for the pet in a single
        image grid, ensuring stylistic consistency across all frames.

        Args:
            owner: Repository owner
            repo: Repository name
            stage: Pet evolution stage
            style: Visual style key
            canonical_appearance: Previously stored appearance description to reuse

        Returns:
            SpriteSheetResult with sprite sheet data and extracted frames
        """
        with _tracer.start_as_current_span(
            "openrouter.generate_sprite_sheet",
            attributes={
                "sprite.owner": owner,
                "sprite.repo": repo,
                "sprite.stage": stage,
                "sprite.style": style,
            },
        ) as span:
            if not self.api_key:
                return SpriteSheetResult(success=False, error="OpenRouter API key not configured")

            try:
                prompt, negative = build_sprite_sheet_prompt(
                    owner, repo, stage, style=style, canonical_appearance=canonical_appearance
                )
                image_data = await self._call_api(prompt, negative)

                if not image_data:
                    return SpriteSheetResult(
                        success=False,
                        error="No image data in OpenRouter sprite sheet response",
                    )

                raw_frames = extract_frames(image_data)
                span.add_event("frames_extracted", {"count": len(raw_frames)})

                appearance_desc = canonical_appearance or get_canonical_appearance_description(
                    owner, repo
                )

                analysis = await analyze_sprite_sheet(image_data, self.api_key or "")
                span.add_event("vision_analysis", {"success": bool(analysis)})

                if analysis:
                    frames = reorder_frames_by_analysis(raw_frames, analysis)
                else:
                    frames = raw_frames

                logger.info(
                    "Sprite sheet generated",
                    owner=owner,
                    repo=repo,
                    stage=stage,
                    raw_frame_count=len(raw_frames),
                    reordered_frame_count=len(frames),
                    vision_analysis=bool(analysis),
                )
                return SpriteSheetResult(
                    success=True,
                    sprite_sheet_data=image_data,
                    frames=frames,
                    canonical_appearance=appearance_desc,
                )

            except httpx.TimeoutException:
                logger.error(
                    "OpenRouter sprite sheet request timed out",
                    owner=owner,
                    repo=repo,
                    stage=stage,
                )
                return SpriteSheetResult(success=False, error="Sprite sheet generation timed out")
            except Exception as e:
                logger.error(
                    "OpenRouter sprite sheet generation failed",
                    owner=owner,
                    repo=repo,
                    stage=stage,
                    error=str(e),
                )
                return SpriteSheetResult(success=False, error=str(e))

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
            logger.warning("openrouter_health_check_failed", exc_info=True)
            return False
