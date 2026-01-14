"""ComfyUI image generation service for pet images."""

import asyncio
import hashlib
from typing import Any

import httpx
import structlog

from github_tamagotchi.core.config import settings
from github_tamagotchi.models.pet import PetStage
from github_tamagotchi.services.storage import StorageService

logger = structlog.get_logger()

# Pet appearance options derived from repo hash
COLORS = [
    "blue",
    "pink",
    "green",
    "purple",
    "orange",
    "yellow",
    "teal",
    "red",
    "lavender",
    "mint",
]

PATTERNS = [
    "spotted",
    "striped",
    "solid",
    "gradient",
    "polka-dotted",
    "star-patterned",
    "swirled",
    "checkered",
]

SPECIES = [
    "blob",
    "bird",
    "cat-like",
    "bunny",
    "dragon",
    "slime",
    "ghost",
    "fox",
    "bear",
    "penguin",
]

STAGE_DESCRIPTIONS = {
    PetStage.EGG.value: "egg with small crack and inner glow",
    PetStage.BABY.value: "tiny newborn blob with huge eyes",
    PetStage.CHILD.value: "small round creature with stubby limbs",
    PetStage.TEEN.value: "growing creature with defined features",
    PetStage.ADULT.value: "fully grown, confident pose",
    PetStage.ELDER.value: "wise ancient creature with crown or beard",
}


def get_repo_hash(owner: str, repo: str) -> bytes:
    """Get deterministic hash bytes for a repository."""
    return hashlib.sha256(f"{owner}/{repo}".encode()).digest()


def get_seed_from_hash(hash_bytes: bytes) -> int:
    """Get a seed value from hash bytes for reproducible generation."""
    return int.from_bytes(hash_bytes[:4], "big")


def get_pet_characteristics(owner: str, repo: str) -> dict[str, str]:
    """Derive pet appearance characteristics from repo hash."""
    hash_bytes = get_repo_hash(owner, repo)

    return {
        "color": COLORS[hash_bytes[0] % len(COLORS)],
        "pattern": PATTERNS[hash_bytes[1] % len(PATTERNS)],
        "species": SPECIES[hash_bytes[2] % len(SPECIES)],
    }


def generate_pet_prompt(owner: str, repo: str, stage: str) -> str:
    """Generate a ComfyUI prompt for a pet image.

    Args:
        owner: Repository owner
        repo: Repository name
        stage: Pet stage (egg, baby, child, teen, adult, elder)

    Returns:
        Prompt string for image generation
    """
    characteristics = get_pet_characteristics(owner, repo)
    stage_desc = STAGE_DESCRIPTIONS.get(stage, "cute creature")

    color = characteristics["color"]
    species = characteristics["species"]
    pattern = characteristics["pattern"]

    return f"""cute pixel art tamagotchi pet, {color} {species} creature,
{pattern} pattern, {stage_desc},
kawaii style, white background, game sprite, centered"""


def build_comfyui_workflow(
    owner: str, repo: str, stage: str
) -> dict[str, Any]:
    """Build a ComfyUI workflow for pet image generation.

    This creates a basic txt2img workflow using the KSampler node.
    The workflow structure should match your ComfyUI setup.
    """
    hash_bytes = get_repo_hash(owner, repo)
    seed = get_seed_from_hash(hash_bytes)
    prompt = generate_pet_prompt(owner, repo, stage)

    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "cfg": 7.0,
                "denoise": 1.0,
                "latent_image": ["5", 0],
                "model": ["4", 0],
                "negative": ["7", 0],
                "positive": ["6", 0],
                "sampler_name": "euler",
                "scheduler": "normal",
                "seed": seed,
                "steps": 20,
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "sd_xl_base_1.0.safetensors",
            },
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "batch_size": 1,
                "height": 512,
                "width": 512,
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": prompt,
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": "blurry, low quality, ugly, deformed, text, watermark",
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2],
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": f"tamagotchi_{owner}_{repo}_{stage}",
                "images": ["8", 0],
            },
        },
    }


class ImageGenerationService:
    """Service for generating pet images using ComfyUI."""

    def __init__(
        self,
        comfyui_url: str | None = None,
        timeout: int | None = None,
        storage: StorageService | None = None,
    ) -> None:
        """Initialize with ComfyUI configuration."""
        self.comfyui_url = comfyui_url or settings.comfyui_url
        self.timeout = timeout or settings.comfyui_timeout_seconds
        self.storage = storage or StorageService()

    async def _queue_prompt(
        self, client: httpx.AsyncClient, workflow: dict[str, Any], client_id: str
    ) -> str:
        """Queue a prompt in ComfyUI and return the prompt_id."""
        response = await client.post(
            f"{self.comfyui_url}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            timeout=30.0,
        )
        response.raise_for_status()
        result: dict[str, str] = response.json()
        return result["prompt_id"]

    async def _wait_for_completion(
        self, client: httpx.AsyncClient, prompt_id: str, poll_interval: float = 2.0
    ) -> dict[str, Any]:
        """Poll for prompt completion and return the history entry."""
        elapsed = 0.0
        while elapsed < self.timeout:
            response = await client.get(
                f"{self.comfyui_url}/history/{prompt_id}",
                timeout=10.0,
            )
            response.raise_for_status()
            history: dict[str, Any] = response.json()

            if prompt_id in history:
                entry: dict[str, Any] = history[prompt_id]
                status = entry.get("status", {})
                if status.get("completed", False):
                    return entry
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI generation failed: {status}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"Image generation timed out after {self.timeout}s")

    async def _download_image(
        self, client: httpx.AsyncClient, filename: str, subfolder: str, image_type: str
    ) -> bytes:
        """Download a generated image from ComfyUI."""
        response = await client.get(
            f"{self.comfyui_url}/view",
            params={
                "filename": filename,
                "subfolder": subfolder,
                "type": image_type,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.content

    async def generate_stage_image(
        self, owner: str, repo: str, stage: str
    ) -> bytes:
        """Generate a single stage image for a pet.

        Args:
            owner: Repository owner
            repo: Repository name
            stage: Pet stage

        Returns:
            PNG image bytes
        """
        if not self.comfyui_url:
            raise ValueError("ComfyUI URL not configured")

        workflow = build_comfyui_workflow(owner, repo, stage)
        client_id = f"{owner}_{repo}_{stage}"

        async with httpx.AsyncClient() as client:
            logger.info(
                "Queueing image generation",
                owner=owner,
                repo=repo,
                stage=stage,
            )

            prompt_id = await self._queue_prompt(client, workflow, client_id)
            logger.debug("Prompt queued", prompt_id=prompt_id)

            history = await self._wait_for_completion(client, prompt_id)

            outputs = history.get("outputs", {})
            for node_output in outputs.values():
                images = node_output.get("images", [])
                if images:
                    img_info = images[0]
                    image_data = await self._download_image(
                        client,
                        img_info["filename"],
                        img_info.get("subfolder", ""),
                        img_info.get("type", "output"),
                    )
                    logger.info(
                        "Generated image",
                        owner=owner,
                        repo=repo,
                        stage=stage,
                        size=len(image_data),
                    )
                    return image_data

            raise RuntimeError("No images found in ComfyUI output")

    async def generate_all_stages(
        self, owner: str, repo: str
    ) -> dict[str, str]:
        """Generate images for all pet stages.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Dictionary mapping stage names to storage paths
        """
        stages = [stage.value for stage in PetStage]
        paths: dict[str, str] = {}

        for stage in stages:
            image_data = await self.generate_stage_image(owner, repo, stage)
            path = await self.storage.upload_image(owner, repo, stage, image_data)
            paths[stage] = path

        logger.info(
            "Generated all stage images",
            owner=owner,
            repo=repo,
            stages=list(paths.keys()),
        )
        return paths

    async def get_or_generate_image(
        self, owner: str, repo: str, stage: str
    ) -> bytes:
        """Get an existing image or generate a new one.

        Args:
            owner: Repository owner
            repo: Repository name
            stage: Pet stage

        Returns:
            PNG image bytes
        """
        existing = await self.storage.get_image(owner, repo, stage)
        if existing:
            logger.debug("Using cached image", owner=owner, repo=repo, stage=stage)
            return existing

        image_data = await self.generate_stage_image(owner, repo, stage)
        await self.storage.upload_image(owner, repo, stage, image_data)
        return image_data

    async def regenerate_images(self, owner: str, repo: str) -> dict[str, str]:
        """Delete existing images and regenerate all stages.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            Dictionary mapping stage names to storage paths
        """
        await self.storage.delete_images(owner, repo)
        return await self.generate_all_stages(owner, repo)
