"""System endpoints: styles, badge-styles, image-provider health, queue stats."""

from fastapi import APIRouter
from pydantic import BaseModel

from github_tamagotchi.api.dependencies import DbSession
from github_tamagotchi.core.config import settings
from github_tamagotchi.services import image_queue
from github_tamagotchi.services.badge import BADGE_STYLES
from github_tamagotchi.services.image_generation import STYLES
from github_tamagotchi.services.image_queue import get_image_provider

router: APIRouter = APIRouter(prefix="/api/v1", tags=["system"])


class StyleInfo(BaseModel):
    id: str
    label: str
    description: str


class ImageProviderHealthResponse(BaseModel):
    provider: str
    available: bool


class QueueStatsResponse(BaseModel):
    pending: int
    processing: int
    completed: int
    failed: int


@router.get("/styles", response_model=list[StyleInfo])
async def list_styles() -> list[StyleInfo]:
    """Return all available pet image styles."""
    return [
        StyleInfo(id=style_id, label=style_def["label"], description=style_def["description"])
        for style_id, style_def in STYLES.items()
    ]


@router.get("/badge-styles", response_model=list[str])
async def list_badge_styles() -> list[str]:
    """Return the available badge style options."""
    return sorted(BADGE_STYLES)


@router.get("/health/image-provider", response_model=ImageProviderHealthResponse)
async def image_provider_health_check() -> ImageProviderHealthResponse:
    """Check image generation provider availability."""
    provider = get_image_provider()
    available = await provider.check_health()
    return ImageProviderHealthResponse(
        provider=settings.image_generation_provider,
        available=available,
    )


@router.get("/admin/queue/stats", response_model=QueueStatsResponse)
async def get_queue_stats(session: DbSession) -> QueueStatsResponse:
    """Get image generation queue statistics."""
    stats = await image_queue.get_queue_stats(session)
    return QueueStatsResponse(
        pending=stats.get("pending", 0),
        processing=stats.get("processing", 0),
        completed=stats.get("completed", 0),
        failed=stats.get("failed", 0),
    )
