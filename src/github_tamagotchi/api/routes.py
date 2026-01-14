"""API routes for pet management."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import PetStage
from github_tamagotchi.services.image_generation import (
    ImageGenerationService,
    get_pet_characteristics,
)
from github_tamagotchi.services.storage import StorageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["pets"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


class PetCreate(BaseModel):
    """Request model for creating a pet."""

    repo_owner: str
    repo_name: str
    name: str


class PetResponse(BaseModel):
    """Response model for pet data."""

    id: int
    repo_owner: str
    repo_name: str
    name: str
    stage: str
    mood: str
    health: int
    experience: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health_check(session: DbSession) -> HealthResponse:
    """Health check endpoint."""
    from github_tamagotchi import __version__

    try:
        await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        logger.exception("Database health check failed")
        db_status = "disconnected"

    return HealthResponse(status="healthy", version=__version__, database=db_status)


@router.post("/pets", response_model=PetResponse)
async def create_pet(pet_data: PetCreate, session: DbSession) -> PetResponse:
    """Create a new pet for a GitHub repository."""
    # TODO: Implement database integration
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/pets/{repo_owner}/{repo_name}", response_model=PetResponse)
async def get_pet(repo_owner: str, repo_name: str, session: DbSession) -> PetResponse:
    """Get pet status for a repository."""
    # TODO: Implement database integration
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.post("/pets/{repo_owner}/{repo_name}/feed")
async def feed_pet(repo_owner: str, repo_name: str, session: DbSession) -> PetResponse:
    """Manually feed the pet (triggered by activity)."""
    # TODO: Implement feeding logic
    raise HTTPException(status_code=501, detail="Not implemented yet")


class ImageGenerationResponse(BaseModel):
    """Response for image generation endpoints."""

    message: str
    stages: list[str]


class PetCharacteristics(BaseModel):
    """Response model for pet appearance characteristics."""

    color: str
    pattern: str
    species: str


@router.get("/pets/{repo_owner}/{repo_name}/characteristics", response_model=PetCharacteristics)
async def get_characteristics(repo_owner: str, repo_name: str) -> PetCharacteristics:
    """Get the deterministic appearance characteristics for a pet.

    These characteristics are derived from the repository hash and are
    consistent across all image generations for this pet.
    """
    chars = get_pet_characteristics(repo_owner, repo_name)
    return PetCharacteristics(**chars)


@router.get(
    "/pets/{repo_owner}/{repo_name}/image/{stage}",
    responses={
        200: {"content": {"image/png": {}}, "description": "Pet image"},
        404: {"description": "Image not found"},
        503: {"description": "Image generation not available"},
    },
)
async def get_pet_image(
    repo_owner: str,
    repo_name: str,
    stage: str,
) -> Response:
    """Get the pet image for a specific stage.

    If the image doesn't exist and ComfyUI is configured, it will be generated.
    If ComfyUI is not configured, returns 503.

    Args:
        repo_owner: GitHub repository owner
        repo_name: GitHub repository name
        stage: Pet stage (egg, baby, child, teen, adult, elder)
    """
    valid_stages = [s.value for s in PetStage]
    if stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage. Must be one of: {', '.join(valid_stages)}",
        )

    storage = StorageService()

    # Check if we have MinIO configured
    if not settings.minio_endpoint:
        raise HTTPException(
            status_code=503,
            detail="Image storage not configured",
        )

    # Try to get existing image
    try:
        image_data = await storage.get_image(repo_owner, repo_name, stage)
    except Exception as e:
        logger.error("Failed to get image from storage: %s", e)
        raise HTTPException(status_code=503, detail="Storage service unavailable") from None

    if image_data:
        return Response(content=image_data, media_type="image/png")

    # If no image exists, try to generate one
    if not settings.image_generation_enabled or not settings.comfyui_url:
        raise HTTPException(
            status_code=404,
            detail="Image not found and generation not available",
        )

    try:
        image_service = ImageGenerationService(storage=storage)
        image_data = await image_service.generate_stage_image(repo_owner, repo_name, stage)
        await storage.upload_image(repo_owner, repo_name, stage, image_data)
        return Response(content=image_data, media_type="image/png")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Image generation timed out") from None
    except Exception as e:
        logger.error("Failed to generate image: %s", e)
        raise HTTPException(status_code=503, detail="Image generation failed") from None


@router.post(
    "/pets/{repo_owner}/{repo_name}/generate-images",
    response_model=ImageGenerationResponse,
)
async def generate_pet_images(repo_owner: str, repo_name: str) -> ImageGenerationResponse:
    """Trigger generation of all stage images for a pet.

    This generates images for all 6 stages (egg, baby, child, teen, adult, elder)
    and stores them in MinIO. Existing images are preserved.
    """
    if not settings.image_generation_enabled:
        raise HTTPException(status_code=503, detail="Image generation is disabled")

    if not settings.comfyui_url:
        raise HTTPException(status_code=503, detail="ComfyUI not configured")

    if not settings.minio_endpoint:
        raise HTTPException(status_code=503, detail="Image storage not configured")

    try:
        storage = StorageService()
        image_service = ImageGenerationService(storage=storage)
        paths = await image_service.generate_all_stages(repo_owner, repo_name)
        return ImageGenerationResponse(
            message="Images generated successfully",
            stages=list(paths.keys()),
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Image generation timed out") from None
    except Exception as e:
        logger.error("Failed to generate images: %s", e)
        raise HTTPException(status_code=503, detail=f"Image generation failed: {e}") from None


@router.post(
    "/pets/{repo_owner}/{repo_name}/regenerate-images",
    response_model=ImageGenerationResponse,
)
async def regenerate_pet_images(repo_owner: str, repo_name: str) -> ImageGenerationResponse:
    """Delete existing images and regenerate all stages.

    Use this to force regeneration if ComfyUI settings or prompts have changed.
    """
    if not settings.image_generation_enabled:
        raise HTTPException(status_code=503, detail="Image generation is disabled")

    if not settings.comfyui_url:
        raise HTTPException(status_code=503, detail="ComfyUI not configured")

    if not settings.minio_endpoint:
        raise HTTPException(status_code=503, detail="Image storage not configured")

    try:
        storage = StorageService()
        image_service = ImageGenerationService(storage=storage)
        paths = await image_service.regenerate_images(repo_owner, repo_name)
        return ImageGenerationResponse(
            message="Images regenerated successfully",
            stages=list(paths.keys()),
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Image generation timed out") from None
    except Exception as e:
        logger.error("Failed to regenerate images: %s", e)
        raise HTTPException(status_code=503, detail=f"Image regeneration failed: {e}") from None
