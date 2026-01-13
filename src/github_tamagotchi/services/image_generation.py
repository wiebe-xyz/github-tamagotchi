"""ComfyUI image generation service for pet sprites."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import structlog

from github_tamagotchi.core.config import settings
from github_tamagotchi.models.pet import PetStage

logger = structlog.get_logger()

# Stage-specific prompt descriptions for visual evolution
STAGE_PROMPTS: dict[str, str] = {
    PetStage.EGG.value: "oval egg shape with subtle crack pattern, soft inner glow",
    PetStage.BABY.value: "tiny blob creature, oversized head, huge sparkly eyes, stubby limbs",
    PetStage.CHILD.value: "small round body, short arms and legs, curious expression, playful",
    PetStage.TEEN.value: "medium sized, more defined limbs, energetic pose, slightly taller",
    PetStage.ADULT.value: "full grown creature, balanced proportions, confident stance, mature",
    PetStage.ELDER.value: "wise ancient creature, small crown or halo, kind eyes, dignified",
}

# Color palettes for pet variation (primary, accent)
COLOR_PALETTES: list[tuple[str, str]] = [
    ("sky blue", "white"),
    ("pink", "lavender"),
    ("mint green", "yellow"),
    ("coral orange", "cream"),
    ("lavender", "periwinkle"),
    ("peach", "coral"),
    ("soft yellow", "orange"),
    ("teal", "aquamarine"),
    ("rose pink", "magenta"),
    ("lime green", "chartreuse"),
    ("baby blue", "navy"),
    ("violet", "plum"),
    ("salmon", "pink"),
    ("turquoise", "cyan"),
    ("apricot", "gold"),
    ("seafoam", "emerald"),
]

# Body types for creature variation
BODY_TYPES: list[str] = [
    "round blob",
    "oval",
    "pear-shaped",
    "bean-shaped",
    "star-shaped",
    "cloud-like",
    "teardrop",
    "mushroom-shaped",
]

# Special features for uniqueness
FEATURES: list[str] = [
    "small antenna",
    "tiny wings",
    "fluffy tail",
    "pointed ears",
    "polka dot spots",
    "striped pattern",
    "heart-shaped marking",
    "star-shaped eyes",
    "rosy cheeks",
    "sparkle effects",
]

# Base prompt templates
POSITIVE_PROMPT_TEMPLATE = (
    "cute pixel art tamagotchi creature, {color} and {accent_color} coloring, "
    "{body_type} body shape, {feature} features, {stage_description}, "
    "kawaii style, game sprite, white background, centered composition, "
    "clean lines, simple shading, full body visible, adorable, chibi"
)

NEGATIVE_PROMPT = (
    "blurry, low quality, realistic, photograph, complex background, "
    "multiple creatures, text, watermark, signature, cropped, "
    "scary, horror, dark, gritty, nsfw, violent, blood"
)


@dataclass
class PetAppearance:
    """Visual characteristics for a pet based on repository identity."""

    color: str
    accent_color: str
    body_type: str
    feature: str
    seed: int


@dataclass
class GenerationResult:
    """Result of image generation."""

    success: bool
    image_data: bytes | None = None
    filename: str | None = None
    error: str | None = None


def repo_to_seed(owner: str, repo: str) -> int:
    """Generate a deterministic seed from repository identity.

    Same owner/repo always produces the same seed for consistent appearance.
    """
    identity = f"{owner.lower()}/{repo.lower()}"
    hash_bytes = hashlib.sha256(identity.encode()).digest()
    # Use first 4 bytes for seed (32-bit integer)
    return int.from_bytes(hash_bytes[:4], byteorder="big")


def get_pet_appearance(owner: str, repo: str) -> PetAppearance:
    """Derive consistent visual characteristics from repository identity.

    The same repository will always have the same appearance.
    """
    seed = repo_to_seed(owner, repo)

    # Use different portions of seed for each attribute
    color_idx = seed % len(COLOR_PALETTES)
    body_idx = (seed >> 8) % len(BODY_TYPES)
    feature_idx = (seed >> 16) % len(FEATURES)

    primary, accent = COLOR_PALETTES[color_idx]

    return PetAppearance(
        color=primary,
        accent_color=accent,
        body_type=BODY_TYPES[body_idx],
        feature=FEATURES[feature_idx],
        seed=seed,
    )


def build_prompt(appearance: PetAppearance, stage: str) -> str:
    """Build the positive prompt for image generation."""
    stage_desc = STAGE_PROMPTS.get(stage, STAGE_PROMPTS[PetStage.ADULT.value])

    return POSITIVE_PROMPT_TEMPLATE.format(
        color=appearance.color,
        accent_color=appearance.accent_color,
        body_type=appearance.body_type,
        feature=appearance.feature,
        stage_description=stage_desc,
    )


def load_base_workflow() -> dict[str, Any]:
    """Load the base ComfyUI workflow from JSON file."""
    workflow_path = Path(__file__).parent.parent / "workflows" / "pet_generation.json"
    with open(workflow_path) as f:
        workflow: dict[str, Any] = json.load(f)
    return workflow


def build_workflow(owner: str, repo: str, stage: str) -> dict[str, Any]:
    """Build a complete ComfyUI workflow for pet generation.

    Args:
        owner: Repository owner
        repo: Repository name
        stage: Pet evolution stage

    Returns:
        Complete workflow dictionary ready for ComfyUI API
    """
    workflow = load_base_workflow()
    appearance = get_pet_appearance(owner, repo)
    prompt = build_prompt(appearance, stage)

    # Update KSampler seed
    workflow["3"]["inputs"]["seed"] = appearance.seed

    # Update positive prompt
    workflow["6"]["inputs"]["text"] = prompt

    # Update filename prefix
    workflow["10"]["inputs"]["filename_prefix"] = f"{owner}_{repo}_{stage}"

    return workflow


class ImageGenerationService:
    """Service for generating pet images via ComfyUI API."""

    def __init__(self, comfyui_url: str | None = None) -> None:
        """Initialize the image generation service.

        Args:
            comfyui_url: ComfyUI server URL (defaults to settings)
        """
        self.comfyui_url = comfyui_url or settings.comfyui_url
        self.timeout = settings.comfyui_timeout

    async def generate_pet_image(
        self, owner: str, repo: str, stage: str
    ) -> GenerationResult:
        """Generate a pet image for the given repository and stage.

        Args:
            owner: Repository owner
            repo: Repository name
            stage: Pet evolution stage (egg, baby, child, teen, adult, elder)

        Returns:
            GenerationResult with image data or error
        """
        try:
            workflow = build_workflow(owner, repo, stage)
            prompt_id = await self._queue_prompt(workflow)

            if not prompt_id:
                return GenerationResult(
                    success=False, error="Failed to queue prompt in ComfyUI"
                )

            # Wait for completion and get image
            image_data = await self._wait_for_image(prompt_id)

            if image_data:
                return GenerationResult(
                    success=True,
                    image_data=image_data,
                    filename=f"{owner}_{repo}_{stage}.png",
                )
            return GenerationResult(
                success=False, error="Failed to retrieve generated image"
            )

        except httpx.TimeoutException:
            logger.error(
                "ComfyUI request timed out",
                owner=owner,
                repo=repo,
                stage=stage,
            )
            return GenerationResult(success=False, error="Image generation timed out")
        except Exception as e:
            logger.error(
                "Image generation failed",
                owner=owner,
                repo=repo,
                stage=stage,
                error=str(e),
            )
            return GenerationResult(success=False, error=str(e))

    async def _queue_prompt(self, workflow: dict[str, Any]) -> str | None:
        """Queue a prompt in ComfyUI and return the prompt ID."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.comfyui_url}/prompt",
                json={"prompt": workflow},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            prompt_id: str | None = data.get("prompt_id")
            return prompt_id

    async def _wait_for_image(
        self, prompt_id: str, max_attempts: int = 60
    ) -> bytes | None:
        """Poll ComfyUI for completion and retrieve the generated image.

        Args:
            prompt_id: The prompt ID to wait for
            max_attempts: Maximum polling attempts (default 60 = ~60 seconds)

        Returns:
            Image data as bytes or None if failed
        """
        import asyncio

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for _ in range(max_attempts):
                # Check history for completion
                response = await client.get(
                    f"{self.comfyui_url}/history/{prompt_id}"
                )
                response.raise_for_status()
                history: dict[str, Any] = response.json()

                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    # Find SaveImage node output (node "10")
                    save_output = outputs.get("10", {})
                    images = save_output.get("images", [])

                    if images:
                        # Get the first image
                        image_info = images[0]
                        return await self._fetch_image(
                            client,
                            image_info["filename"],
                            image_info.get("subfolder", ""),
                            image_info.get("type", "output"),
                        )

                await asyncio.sleep(1)

        return None

    async def _fetch_image(
        self,
        client: httpx.AsyncClient,
        filename: str,
        subfolder: str,
        image_type: str,
    ) -> bytes:
        """Fetch an image from ComfyUI output directory."""
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": image_type,
        }
        response = await client.get(f"{self.comfyui_url}/view", params=params)
        response.raise_for_status()
        return response.content

    async def check_health(self) -> bool:
        """Check if ComfyUI server is reachable and healthy."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.comfyui_url}/system_stats")
                return response.status_code == 200
        except Exception:
            return False
