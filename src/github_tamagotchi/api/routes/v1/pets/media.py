"""Pet media endpoints: badge SVG, static image, animated GIF, generate/regenerate."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.schemas.pets import ImageGenerationResponse
from github_tamagotchi.services import pet as pet_service
from github_tamagotchi.services.badge import BADGE_STYLES
from github_tamagotchi.services.image_generation import DEFAULT_STYLE
from github_tamagotchi.services.sprite_sheet import compose_animated_gif
from github_tamagotchi.services.storage import StorageService

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/api/v1", tags=["pets"])

# Shared headers for SVG badge responses
_SVG_HEADERS = {
    "Cache-Control": "public, max-age=300, stale-while-revalidate=60",
    "Content-Type": "image/svg+xml; charset=utf-8",
}


def get_storage_service() -> StorageService:
    return _api_routes.StorageService()


StorageDep = Annotated[StorageService, Depends(get_storage_service)]


def _require_image_generation() -> None:
    """Raise 503 if image generation or storage is not configured."""
    if not _api_routes.settings.image_generation_enabled:
        raise HTTPException(status_code=503, detail="Image generation is disabled")
    if not _api_routes.settings.minio_endpoint:
        raise HTTPException(status_code=503, detail="Image storage not configured")


async def _generate_all_stages(
    repo_owner: str,
    repo_name: str,
    storage: StorageService,
    session: AsyncSession,
) -> list[str]:
    """Generate images for all pet stages and upload them. Returns list of generated stage names."""
    image_service = _api_routes.get_image_provider()
    generated_stages = []
    for pet_stage in PetStage:
        result = await image_service.generate_pet_image(repo_owner, repo_name, pet_stage.value)
        if result.success and result.image_data:
            await storage.upload_image(repo_owner, repo_name, pet_stage.value, result.image_data)
            generated_stages.append(pet_stage.value)
    await pet_service.update_images_generated_at(session, repo_owner, repo_name)
    return generated_stages


@router.get("/pets/{repo_owner}/{repo_name}/badge.svg", response_class=Response)
async def get_pet_badge(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    style: str | None = Query(default=None, description="Badge style override"),
) -> Response:
    """Return an SVG badge representing the current pet state."""
    import base64

    from github_tamagotchi.services.badge import generate_badge_svg

    if style is not None and style not in BADGE_STYLES:
        valid = ", ".join(sorted(BADGE_STYLES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid badge style '{style}'. Must be one of: {valid}",
        )

    pet = await get_pet_or_404(repo_owner, repo_name, session)

    pet_image_b64: str | None = None
    try:
        storage = _api_routes.StorageService()
        image_bytes = await storage.get_image(pet.repo_owner, pet.repo_name, pet.stage)
        if image_bytes:
            pet_image_b64 = base64.b64encode(image_bytes).decode()
    except Exception:
        logger.warning(
            "badge_image_load_failed",
            repo=f"{pet.repo_owner}/{pet.repo_name}",
            stage=pet.stage,
            exc_info=True,
        )

    unlocked_achievements: set[str] = set()
    try:
        from github_tamagotchi.services.achievements import get_unlocked_achievement_ids
        unlocked_achievements = await get_unlocked_achievement_ids(pet.id, session)
    except Exception:
        logger.warning("Failed to load achievements for badge", exc_info=True)

    svg_content = generate_badge_svg(
        pet.name,
        pet.stage,
        pet.mood,
        pet.health,
        is_dead=pet.is_dead,
        died_at=pet.died_at,
        created_at=pet.created_at,
        commit_streak=pet.commit_streak,
        pet_image_b64=pet_image_b64,
        badge_style=style if style is not None else pet.badge_style,
        dependent_count=pet.dependent_count,
        unlocked_achievements=unlocked_achievements,
    )
    return Response(content=svg_content, media_type="image/svg+xml", headers=_SVG_HEADERS)


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
    session: DbSession,
    storage: StorageDep,
) -> Response:
    """Get the pet image for a specific stage, generating on-demand if needed."""
    valid_stages = [s.value for s in PetStage]
    if stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage. Must be one of: {', '.join(valid_stages)}",
        )
    if not _api_routes.settings.minio_endpoint:
        raise HTTPException(status_code=503, detail="Image storage not configured")

    try:
        image_data = await storage.get_image(repo_owner, repo_name, stage)
    except Exception as e:
        logger.error("Failed to get image from storage: %s", e)
        raise HTTPException(status_code=503, detail="Storage service unavailable") from None

    if image_data:
        return Response(
            content=image_data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    if not _api_routes.settings.image_generation_enabled:
        raise HTTPException(status_code=404, detail="Image not found and generation not available")

    try:
        image_service = _api_routes.get_image_provider()
        result = await image_service.generate_pet_image(repo_owner, repo_name, stage)
        if not result.success or not result.image_data:
            raise HTTPException(status_code=503, detail=result.error or "Image generation failed")
        await storage.upload_image(repo_owner, repo_name, stage, result.image_data)
        await pet_service.update_images_generated_at(session, repo_owner, repo_name)
        return Response(
            content=result.image_data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Image generation timed out") from None
    except Exception as e:
        logger.error("Failed to generate image: %s", e)
        raise HTTPException(status_code=503, detail="Image generation failed") from None


@router.get(
    "/pets/{repo_owner}/{repo_name}/image/{stage}/animated",
    responses={
        200: {"content": {"image/gif": {}}, "description": "Animated pet GIF"},
        404: {"description": "Animated GIF not found"},
        503: {"description": "Sprite sheet generation not available"},
    },
)
async def get_pet_animated_gif(
    repo_owner: str,
    repo_name: str,
    stage: str,
    session: DbSession,
    storage: StorageDep,
) -> Response:
    """Get the animated GIF for a pet at a specific stage, generating on demand."""
    valid_stages = [s.value for s in PetStage]
    if stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage. Must be one of: {', '.join(valid_stages)}",
        )
    if not _api_routes.settings.minio_endpoint:
        raise HTTPException(status_code=503, detail="Image storage not configured")

    try:
        gif_data = await storage.get_animated_gif(repo_owner, repo_name, stage)
    except Exception as e:
        logger.error("Failed to get animated GIF from storage: %s", e)
        raise HTTPException(status_code=503, detail="Storage service unavailable") from None

    if gif_data:
        return Response(
            content=gif_data,
            media_type="image/gif",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    s = _api_routes.settings
    if not s.image_generation_enabled or s.image_generation_provider != "openrouter":
        raise HTTPException(
            status_code=404,
            detail=(
                "Animated GIF not found and sprite sheet generation "
                "requires OpenRouter provider"
            ),
        )

    pet: Pet | None = await pet_service.get_by_repo(session, repo_owner, repo_name)
    mood = pet.mood if pet else "content"
    health = pet.health if pet else 100
    style = pet.style if pet else DEFAULT_STYLE
    stored_appearance = pet.canonical_appearance if pet else None

    try:
        openrouter = _api_routes.OpenRouterService()
        sheet_result = await openrouter.generate_sprite_sheet(
            repo_owner,
            repo_name,
            stage,
            style=style,
            canonical_appearance=stored_appearance,
        )
    except Exception as e:
        logger.error("Sprite sheet generation failed: %s", e)
        raise HTTPException(status_code=503, detail="Sprite sheet generation failed") from None

    if not sheet_result.success or not sheet_result.sprite_sheet_data:
        raise HTTPException(
            status_code=503,
            detail=sheet_result.error or "Sprite sheet generation failed",
        )

    try:
        await storage.upload_sprite_sheet(
            repo_owner, repo_name, stage, sheet_result.sprite_sheet_data
        )
        for idx, frame_bytes in enumerate(sheet_result.frames):
            await storage.upload_frame(repo_owner, repo_name, stage, idx, frame_bytes)
    except Exception as e:
        logger.warning("Failed to store sprite sheet assets: %s", e)

    try:
        gif_data = compose_animated_gif(sheet_result.frames, mood=mood, health=health)
    except Exception as e:
        logger.error("GIF composition failed: %s", e)
        raise HTTPException(status_code=503, detail="GIF composition failed") from None

    try:
        await storage.upload_animated_gif(repo_owner, repo_name, stage, gif_data)
    except Exception as e:
        logger.warning("Failed to store animated GIF: %s", e)

    if pet and not pet.canonical_appearance and sheet_result.canonical_appearance:
        try:
            await pet_service.update_canonical_appearance(
                session, repo_owner, repo_name, sheet_result.canonical_appearance
            )
        except Exception as e:
            logger.warning("Failed to update canonical appearance: %s", e)

    return Response(
        content=gif_data,
        media_type="image/gif",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post(
    "/pets/{repo_owner}/{repo_name}/generate-images",
    response_model=ImageGenerationResponse,
)
async def generate_pet_images(
    repo_owner: str, repo_name: str, session: DbSession, storage: StorageDep
) -> ImageGenerationResponse:
    """Trigger generation of all stage images for a pet."""
    _require_image_generation()
    try:
        generated_stages = await _generate_all_stages(repo_owner, repo_name, storage, session)
        return ImageGenerationResponse(
            message="Images generated successfully", stages=generated_stages
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Image generation timed out") from None
    except Exception as e:
        logger.error("Failed to generate images: %s", e)
        raise HTTPException(status_code=503, detail="Image generation failed") from None


@router.post(
    "/pets/{repo_owner}/{repo_name}/regenerate-images",
    response_model=ImageGenerationResponse,
)
async def regenerate_pet_images(
    repo_owner: str, repo_name: str, session: DbSession, storage: StorageDep
) -> ImageGenerationResponse:
    """Delete existing images and regenerate all stages."""
    _require_image_generation()
    try:
        await storage.delete_images(repo_owner, repo_name)
        generated_stages = await _generate_all_stages(repo_owner, repo_name, storage, session)
        return ImageGenerationResponse(
            message="Images regenerated successfully", stages=generated_stages
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Image generation timed out") from None
    except Exception as e:
        logger.error("Failed to regenerate images: %s", e)
        raise HTTPException(status_code=503, detail="Image regeneration failed") from None
