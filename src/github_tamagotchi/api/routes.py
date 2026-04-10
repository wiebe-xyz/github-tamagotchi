"""API routes for pet management."""

import logging
import math
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from github_tamagotchi.api.auth import get_current_user, get_optional_user
from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import get_session
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.models.webhook_event import WebhookEvent
from github_tamagotchi.services import image_queue
from github_tamagotchi.services.badge import BADGE_STYLES
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.image_generation import DEFAULT_STYLE, STYLES, get_pet_appearance
from github_tamagotchi.services.image_queue import get_image_provider
from github_tamagotchi.services.naming import generate_name_from_repo, is_valid_pet_name
from github_tamagotchi.services.storage import StorageService
from github_tamagotchi.services.token_encryption import decrypt_token
from github_tamagotchi.services.webhook import EVENT_HANDLERS, verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["pets"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


def get_storage_service() -> StorageService:
    """Dependency that provides a shared StorageService instance."""
    return StorageService()


StorageDep = Annotated[StorageService, Depends(get_storage_service)]


class PetCreate(BaseModel):
    """Request model for creating a pet."""

    repo_owner: str = Field(..., min_length=1, max_length=255)
    repo_name: str = Field(..., min_length=1, max_length=255)
    name: str | None = Field(None, min_length=1, max_length=20)
    style: str = Field(DEFAULT_STYLE, min_length=1, max_length=30)


class StyleInfo(BaseModel):
    """A single style definition."""

    id: str
    label: str
    description: str


class StyleUpdateRequest(BaseModel):
    """Request body for updating a pet's style."""

    style: str = Field(..., min_length=1, max_length=30)


class PetRenameRequest(BaseModel):
    """Request body for renaming a pet."""

    name: str = Field(..., min_length=1, max_length=20)


class BadgeStyleUpdateRequest(BaseModel):
    """Request body for updating a pet's badge style."""

    badge_style: str = Field(..., min_length=1, max_length=20)


class PetResponse(BaseModel):
    """Response model for pet data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_owner: str
    repo_name: str
    name: str
    stage: str
    mood: str
    health: int
    experience: int
    style: str
    badge_style: str
    commit_streak: int
    longest_streak: int
    generation: int
    is_dead: bool
    died_at: datetime | None
    cause_of_death: str | None
    created_at: datetime
    updated_at: datetime
    last_fed_at: datetime | None
    last_checked_at: datetime | None


class PetListResponse(BaseModel):
    """Response model for paginated pet list."""

    items: list[PetResponse]
    total: int
    page: int
    per_page: int
    pages: int


class FeedResponse(BaseModel):
    """Response model for feed action."""

    message: str
    pet: PetResponse


class WebhookResponse(BaseModel):
    """Response for webhook processing."""

    status: str
    message: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str


class ImageProviderHealthResponse(BaseModel):
    """Image provider health check response."""

    provider: str
    available: bool


class QueueStatsResponse(BaseModel):
    """Queue statistics response."""

    pending: int
    processing: int
    completed: int
    failed: int


class ImageGenerationResponse(BaseModel):
    """Response for image generation endpoints."""

    message: str
    stages: list[str]


class PetCharacteristics(BaseModel):
    """Response model for pet appearance characteristics."""

    color: str
    accent_color: str
    body_type: str
    feature: str


class RepoItem(BaseModel):
    """A GitHub repo available for pet registration."""

    full_name: str
    owner: str
    name: str
    description: str | None
    private: bool
    has_pet: bool
    pet_name: str | None


class CommentResponse(BaseModel):
    """Response model for a single comment."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    author_name: str
    body: str
    created_at: datetime


class CommentsListResponse(BaseModel):
    """Response model for a list of comments."""

    comments: list[CommentResponse]


class CommentCreate(BaseModel):
    """Request body for creating a comment."""

    body: str = Field(..., min_length=1, max_length=500)


class AchievementItem(BaseModel):
    """A single achievement with unlock status."""

    id: str
    name: str
    icon: str
    description: str
    unlocked: bool
    unlocked_at: datetime | None


class AchievementsResponse(BaseModel):
    """Response model for the achievements list."""

    achievements: list[AchievementItem]


class MilestoneItem(BaseModel):
    """A single evolution milestone."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    old_stage: str
    new_stage: str
    experience: int
    age_days: int
    created_at: datetime


class MilestonesResponse(BaseModel):
    """Response model for the milestones list."""

    milestones: list[MilestoneItem]


class BlameEntryItem(BaseModel):
    """A single blame entry on the blame board."""

    issue: str
    culprit: str
    how_long: str


class HeroEntryItem(BaseModel):
    """A single hero entry on the heroes board."""

    good_deed: str
    hero: str
    when: str


class BlameBoardResponse(BaseModel):
    """Response model for the blame/heroes board."""

    is_healthy: bool
    blame_board_enabled: bool
    blame_entries: list[BlameEntryItem]
    hero_entries: list[HeroEntryItem]


class LeaderboardEntry(BaseModel):
    """A single entry on the leaderboard."""

    model_config = ConfigDict(from_attributes=True)

    rank: int
    pet_name: str
    repo_owner: str
    repo_name: str
    stage: str
    value: int


class LeaderboardCategory(BaseModel):
    """A leaderboard category with its ranked entries."""

    id: str
    title: str
    description: str
    entries: list[LeaderboardEntry]


class LeaderboardResponse(BaseModel):
    """Response model for the full leaderboard."""

    categories: list[LeaderboardCategory]
    cached_at: datetime


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


@router.get("/styles", response_model=list[StyleInfo])
async def list_styles() -> list[StyleInfo]:
    """Return all available pet image styles."""
    return [
        StyleInfo(id=style_id, label=style_def["label"], description=style_def["description"])
        for style_id, style_def in STYLES.items()
    ]


@router.post("/pets", response_model=PetResponse, status_code=status.HTTP_201_CREATED)
async def create_pet(
    pet_data: PetCreate,
    session: DbSession,
    user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> PetResponse:
    """Create a new pet for a GitHub repository."""
    if pet_data.style not in STYLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid style '{pet_data.style}'. Must be one of: {', '.join(STYLES.keys())}",
        )
    existing = await pet_crud.get_pet_by_repo(session, pet_data.repo_owner, pet_data.repo_name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pet already exists for {pet_data.repo_owner}/{pet_data.repo_name}",
        )
    # Generate a name from the repo if none was provided
    if pet_data.name is None:
        pet_name = generate_name_from_repo(pet_data.repo_owner, pet_data.repo_name)
    else:
        if not is_valid_pet_name(pet_data.name):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid pet name. Use 1-20 alphanumeric chars and spaces, no profanity.",
            )
        pet_name = pet_data.name
    pet = await pet_crud.create_pet(
        session,
        pet_data.repo_owner,
        pet_data.repo_name,
        pet_name,
        user_id=user.id if user else None,
        style=pet_data.style,
    )
    # Enqueue egg stage image generation if a provider is configured
    try:
        get_image_provider()
        await image_queue.create_job(session, pet.id, PetStage.EGG.value)
    except ValueError:
        pass  # no valid provider configured, skip
    return PetResponse.model_validate(pet)


@router.get("/pets", response_model=PetListResponse)
async def list_pets(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 10,
) -> PetListResponse:
    """List all pets with pagination."""
    pets, total = await pet_crud.get_pets(session, page=page, per_page=per_page)
    pages = math.ceil(total / per_page) if total > 0 else 1
    return PetListResponse(
        items=[PetResponse.model_validate(p) for p in pets],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get("/pets/{repo_owner}/{repo_name}", response_model=PetResponse)
async def get_pet(repo_owner: str, repo_name: str, session: DbSession) -> PetResponse:
    """Get pet status for a repository."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    return PetResponse.model_validate(pet)


@router.post("/pets/{repo_owner}/{repo_name}/feed", response_model=FeedResponse)
async def feed_pet(repo_owner: str, repo_name: str, session: DbSession) -> FeedResponse:
    """Manually feed the pet (triggered by activity)."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    updated_pet = await pet_crud.feed_pet(session, pet)
    return FeedResponse(
        message=f"{updated_pet.name} has been fed!",
        pet=PetResponse.model_validate(updated_pet),
    )


@router.post("/pets/{repo_owner}/{repo_name}/resurrect", response_model=PetResponse)
async def resurrect_pet(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetResponse:
    """Resurrect a dead pet after the mandatory 7-day mourning period."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    if not pet.is_dead:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pet is not dead and cannot be resurrected",
        )
    if pet.user_id != user.id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this pet",
        )
    if pet.died_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pet death timestamp is missing",
        )
    now = datetime.now(UTC)
    died_at = pet.died_at
    if died_at.tzinfo is None:
        died_at = died_at.replace(tzinfo=UTC)
    days_elapsed = (now - died_at).total_seconds() / 86400
    mourning_days = 7
    if days_elapsed < mourning_days:
        days_remaining = math.ceil(mourning_days - days_elapsed)
        day_word = "day" if days_remaining == 1 else "days"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Your pet must rest for {days_remaining} more {day_word} before resurrection",
        )
    # Perform resurrection
    pet.is_dead = False
    pet.died_at = None
    pet.cause_of_death = None
    pet.grace_period_started = None
    pet.stage = PetStage.EGG.value
    pet.health = 60
    pet.experience = 0
    pet.mood = PetMood.CONTENT.value
    pet.generation += 1
    await session.commit()
    await session.refresh(pet)
    # Enqueue egg stage image generation for the new generation
    try:
        get_image_provider()
        await image_queue.create_job(session, pet.id, PetStage.EGG.value)
    except ValueError:
        pass  # no valid provider configured, skip
    return PetResponse.model_validate(pet)


@router.get("/pets/{repo_owner}/{repo_name}/badge.svg", response_class=Response)
async def get_pet_badge(repo_owner: str, repo_name: str, session: DbSession) -> Response:
    """Return an SVG badge representing the current pet state."""
    import base64

    from github_tamagotchi.services.badge import generate_badge_svg

    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )

    # Attempt to fetch the stage-appropriate sprite; fall back to None (emoji) on any error.
    pet_image_b64: str | None = None
    try:
        storage = StorageService()
        image_bytes = await storage.get_image(pet.repo_owner, pet.repo_name, pet.stage)
        if image_bytes:
            pet_image_b64 = base64.b64encode(image_bytes).decode()
    except Exception:
        pass  # non-fatal — badge will use emoji fallback

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
        badge_style=pet.badge_style,
    )
    return Response(
        content=svg_content,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=300, stale-while-revalidate=60",
            "Content-Type": "image/svg+xml; charset=utf-8",
        },
    )


@router.delete("/pets/{repo_owner}/{repo_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pet(repo_owner: str, repo_name: str, session: DbSession) -> None:
    """Delete a pet."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    await pet_crud.delete_pet(session, pet)


@router.put("/pets/{repo_owner}/{repo_name}/style", response_model=PetResponse)
async def update_pet_style(
    repo_owner: str,
    repo_name: str,
    style_data: StyleUpdateRequest,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetResponse:
    """Update a pet's style and enqueue image regeneration for its current stage."""
    if style_data.style not in STYLES:
        valid = ", ".join(STYLES.keys())
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid style '{style_data.style}'. Must be one of: {valid}",
        )
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    # Verify ownership
    if pet.user_id != user.id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this pet",
        )
    pet.style = style_data.style
    await session.commit()
    await session.refresh(pet)
    # Enqueue image regeneration for the current stage
    try:
        get_image_provider()
        await image_queue.create_job(session, pet.id, pet.stage)
    except ValueError:
        pass  # no valid provider configured, skip
    return PetResponse.model_validate(pet)


@router.put("/pets/{repo_owner}/{repo_name}/name", response_model=PetResponse)
async def rename_pet(
    repo_owner: str,
    repo_name: str,
    rename_data: PetRenameRequest,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetResponse:
    """Rename a pet. Requires ownership."""
    if not is_valid_pet_name(rename_data.name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid pet name. Use 1-20 alphanumeric characters and spaces, no profanity.",
        )
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    if pet.user_id != user.id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this pet",
        )
    pet.name = rename_data.name
    await session.commit()
    await session.refresh(pet)
    return PetResponse.model_validate(pet)


@router.put("/pets/{repo_owner}/{repo_name}/badge-style", response_model=PetResponse)
async def update_pet_badge_style(
    repo_owner: str,
    repo_name: str,
    badge_style_data: BadgeStyleUpdateRequest,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetResponse:
    """Update the badge visual style for a pet. Requires ownership."""
    if badge_style_data.badge_style not in BADGE_STYLES:
        valid = ", ".join(sorted(BADGE_STYLES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid badge style '{badge_style_data.badge_style}'. Must be one of: {valid}",
        )
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    if pet.user_id != user.id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this pet",
        )
    pet.badge_style = badge_style_data.badge_style
    await session.commit()
    await session.refresh(pet)
    return PetResponse.model_validate(pet)


@router.get("/badge-styles", response_model=list[str])
async def list_badge_styles() -> list[str]:
    """Return the available badge style options."""
    return sorted(BADGE_STYLES)


@router.get("/pets/{repo_owner}/{repo_name}/characteristics", response_model=PetCharacteristics)
async def get_characteristics(repo_owner: str, repo_name: str) -> PetCharacteristics:
    """Get the deterministic appearance characteristics for a pet."""
    appearance = get_pet_appearance(repo_owner, repo_name)
    return PetCharacteristics(
        color=appearance.color,
        accent_color=appearance.accent_color,
        body_type=appearance.body_type,
        feature=appearance.feature,
    )


@router.get("/pets/{repo_owner}/{repo_name}/comments", response_model=CommentsListResponse)
async def list_comments(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    _user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> CommentsListResponse:
    """Return the newest 50 comments for a pet profile."""
    from sqlalchemy import select as sa_select

    from github_tamagotchi.models.comment import PetComment

    result = await session.execute(
        sa_select(PetComment)
        .where(PetComment.repo_owner == repo_owner, PetComment.repo_name == repo_name)
        .order_by(PetComment.created_at.desc())
        .limit(50)
    )
    comments = result.scalars().all()
    return CommentsListResponse(
        comments=[CommentResponse.model_validate(c) for c in comments]
    )


@router.post(
    "/pets/{repo_owner}/{repo_name}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    repo_owner: str,
    repo_name: str,
    comment_data: CommentCreate,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> CommentResponse:
    """Post a comment on a pet profile. Requires authentication."""
    from github_tamagotchi.models.comment import PetComment

    comment = PetComment(
        repo_owner=repo_owner,
        repo_name=repo_name,
        user_id=user.id,
        author_name=user.github_login,
        body=comment_data.body,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return CommentResponse.model_validate(comment)


@router.get("/pets/{repo_owner}/{repo_name}/achievements", response_model=AchievementsResponse)
async def get_pet_achievements(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
) -> AchievementsResponse:
    """Get all achievements for a pet, with unlock status. Public endpoint."""
    from github_tamagotchi.services.achievements import (
        ACHIEVEMENT_ORDER,
        ACHIEVEMENTS,
    )
    from github_tamagotchi.services.achievements import (
        get_pet_achievements as _get_pet_achievements,
    )

    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )

    achievement_map = await _get_pet_achievements(pet.id, session)
    items = []
    for aid in ACHIEVEMENT_ORDER:
        row = achievement_map[aid]
        items.append(
            AchievementItem(
                id=aid,
                name=ACHIEVEMENTS[aid]["name"],
                icon=ACHIEVEMENTS[aid]["icon"],
                description=ACHIEVEMENTS[aid]["description"],
                unlocked=row is not None,
                unlocked_at=row.unlocked_at if row is not None else None,
            )
        )
    return AchievementsResponse(achievements=items)

@router.get("/pets/{repo_owner}/{repo_name}/milestones", response_model=MilestonesResponse)
async def get_pet_milestones(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
) -> MilestonesResponse:
    """Get recent evolution milestones for a pet. Public endpoint."""
    from github_tamagotchi.crud.milestone import get_milestones

    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )

    milestones = await get_milestones(session, pet.id)
    return MilestonesResponse(
        milestones=[MilestoneItem.model_validate(m) for m in milestones]
    )


@router.get("/pets/{repo_owner}/{repo_name}/blame-board", response_model=BlameBoardResponse)
async def get_blame_board(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
) -> BlameBoardResponse:
    """Get the blame/heroes board for a pet. Public endpoint.

    Returns blame entries when the pet is unhealthy, and hero entries when healthy.
    Returns empty lists when blame_board_enabled is False.
    """
    from github_tamagotchi.services.github import GitHubService

    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )

    if not pet.blame_board_enabled or pet.is_dead:
        return BlameBoardResponse(
            is_healthy=pet.health >= 50,
            blame_board_enabled=pet.blame_board_enabled,
            blame_entries=[],
            hero_entries=[],
        )

    gh = GitHubService()
    board = await gh.get_blame_board_data(
        repo_owner, repo_name, pet.health, pet.mood
    )

    return BlameBoardResponse(
        is_healthy=board.is_healthy,
        blame_board_enabled=True,
        blame_entries=[
            BlameEntryItem(issue=e.issue, culprit=e.culprit, how_long=e.how_long)
            for e in board.blame_entries
        ],
        hero_entries=[
            HeroEntryItem(good_deed=e.good_deed, hero=e.hero, when=e.when)
            for e in board.hero_entries
        ],
    )


async def _update_images_generated_at(
    session: AsyncSession, repo_owner: str, repo_name: str
) -> None:
    """Update the images_generated_at timestamp for a pet if it exists."""
    await session.execute(
        update(Pet)
        .where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
        .values(images_generated_at=func.now())
    )
    await session.commit()


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
    """Get the pet image for a specific stage.

    If the image doesn't exist and ComfyUI is configured, it will be generated.
    If ComfyUI is not configured, returns 503.
    """
    valid_stages = [s.value for s in PetStage]
    if stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage. Must be one of: {', '.join(valid_stages)}",
        )

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
        return Response(
            content=image_data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # If no image exists, try to generate one
    if not settings.image_generation_enabled:
        raise HTTPException(
            status_code=404,
            detail="Image not found and generation not available",
        )

    try:
        image_service = get_image_provider()
        result = await image_service.generate_pet_image(repo_owner, repo_name, stage)
        if not result.success or not result.image_data:
            raise HTTPException(status_code=503, detail=result.error or "Image generation failed")
        await storage.upload_image(repo_owner, repo_name, stage, result.image_data)
        await _update_images_generated_at(session, repo_owner, repo_name)
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


@router.post(
    "/pets/{repo_owner}/{repo_name}/generate-images",
    response_model=ImageGenerationResponse,
)
async def generate_pet_images(
    repo_owner: str, repo_name: str, session: DbSession, storage: StorageDep
) -> ImageGenerationResponse:
    """Trigger generation of all stage images for a pet."""
    if not settings.image_generation_enabled:
        raise HTTPException(status_code=503, detail="Image generation is disabled")

    if not settings.minio_endpoint:
        raise HTTPException(status_code=503, detail="Image storage not configured")

    try:
        image_service = get_image_provider()
        generated_stages = []
        for pet_stage in PetStage:
            result = await image_service.generate_pet_image(repo_owner, repo_name, pet_stage.value)
            if result.success and result.image_data:
                await storage.upload_image(
                    repo_owner, repo_name, pet_stage.value, result.image_data
                )
                generated_stages.append(pet_stage.value)
        await _update_images_generated_at(session, repo_owner, repo_name)
        return ImageGenerationResponse(
            message="Images generated successfully",
            stages=generated_stages,
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
    if not settings.image_generation_enabled:
        raise HTTPException(status_code=503, detail="Image generation is disabled")

    if not settings.minio_endpoint:
        raise HTTPException(status_code=503, detail="Image storage not configured")

    try:
        await storage.delete_images(repo_owner, repo_name)
        image_service = get_image_provider()
        generated_stages = []
        for pet_stage in PetStage:
            result = await image_service.generate_pet_image(repo_owner, repo_name, pet_stage.value)
            if result.success and result.image_data:
                await storage.upload_image(
                    repo_owner, repo_name, pet_stage.value, result.image_data
                )
                generated_stages.append(pet_stage.value)
        await _update_images_generated_at(session, repo_owner, repo_name)
        return ImageGenerationResponse(
            message="Images regenerated successfully",
            stages=generated_stages,
        )
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Image generation timed out") from None
    except Exception as e:
        logger.error("Failed to regenerate images: %s", e)
        raise HTTPException(status_code=503, detail="Image regeneration failed") from None


@router.get("/me/pets", response_model=PetListResponse)
async def list_my_pets(
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 10,
) -> PetListResponse:
    """List pets belonging to the authenticated user."""
    pets, total = await pet_crud.get_pets(session, page=page, per_page=per_page, user_id=user.id)
    pages = math.ceil(total / per_page) if total > 0 else 1
    return PetListResponse(
        items=[PetResponse.model_validate(p) for p in pets],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get("/me/repos", response_model=list[RepoItem])
async def list_my_repos(
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
) -> list[RepoItem]:
    """List GitHub repos accessible to the authenticated user with write access."""
    if not user.encrypted_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No GitHub token stored. Please re-authenticate.",
        )

    try:
        token = decrypt_token(user.encrypted_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to decrypt GitHub token. Please re-authenticate.",
        ) from None

    github = GitHubService(token=token)
    raw_repos = await github.list_user_repos(page=page)

    # Filter to repos where user has push access
    writable = [r for r in raw_repos if r.get("permissions", {}).get("push")]

    # Fetch existing pets to mark which repos already have one
    from sqlalchemy import select as sa_select

    existing_pets: dict[tuple[str, str], str] = {}
    if writable:
        result = await session.execute(sa_select(Pet))
        for pet in result.scalars().all():
            existing_pets[(pet.repo_owner, pet.repo_name)] = pet.name

    return [
        RepoItem(
            full_name=r["full_name"],
            owner=r["owner"]["login"],
            name=r["name"],
            description=r.get("description"),
            private=r.get("private", False),
            has_pet=(r["owner"]["login"], r["name"]) in existing_pets,
            pet_name=existing_pets.get((r["owner"]["login"], r["name"])),
        )
        for r in writable
    ]


@router.post("/webhooks/github", response_model=WebhookResponse)
async def github_webhook(request: Request, session: DbSession) -> WebhookResponse:
    """Receive GitHub webhook events and update pet state."""
    body = await request.body()

    # Verify signature if webhook secret is configured
    if settings.github_webhook_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not signature or not verify_signature(body, signature, settings.github_webhook_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    event_type = request.headers.get("X-GitHub-Event", "")
    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-GitHub-Event header",
        )

    # Handle ping event (sent when webhook is first configured)
    if event_type == "ping":
        return WebhookResponse(status="ok", message="pong")

    handler = EVENT_HANDLERS.get(event_type)
    if not handler:
        return WebhookResponse(
            status="ignored",
            message=f"event type '{event_type}' is not handled",
        )

    payload = await request.json()

    # Extract common fields for logging
    repo = payload.get("repository", {})
    repo_owner = repo.get("owner", {}).get("login", "") if isinstance(repo, dict) else ""
    repo_name = repo.get("name", "") if isinstance(repo, dict) else ""
    action = payload.get("action") if isinstance(payload, dict) else None

    # Build a short human-readable summary
    payload_summary: str | None = None
    try:
        if event_type == "push":
            commits = payload.get("commits", [])
            branch = payload.get("ref", "").removeprefix("refs/heads/")
            payload_summary = f"pushed {len(commits)} commit(s) to {branch}"
        elif event_type == "pull_request":
            pr = payload.get("pull_request", {})
            pr_number = pr.get("number", "?")
            pr_title = pr.get("title", "")
            payload_summary = f"{action} PR #{pr_number}: {pr_title}"
        elif event_type == "issues":
            issue = payload.get("issue", {})
            issue_number = issue.get("number", "?")
            issue_title = issue.get("title", "")
            payload_summary = f"{action} issue #{issue_number}: {issue_title}"
        elif event_type == "check_run":
            check_run = payload.get("check_run", {})
            name = check_run.get("name", "")
            conclusion = check_run.get("conclusion") or check_run.get("status", "")
            payload_summary = f"check run '{name}' {conclusion}"
    except Exception:
        pass  # Summary is best-effort; never block the webhook

    processed = False
    message = await handler(payload, session)
    processed = True

    # Log the event; don't let logging failure crash the webhook
    try:
        event_log = WebhookEvent(
            repo_owner=repo_owner,
            repo_name=repo_name,
            event_type=event_type,
            action=action,
            payload_summary=payload_summary,
            processed=processed,
        )
        session.add(event_log)
        await session.flush()
    except Exception:
        logger.exception("Failed to log webhook event")

    return WebhookResponse(status="processed", message=message)


_LEADERBOARD_CATEGORIES = [
    {
        "id": "most_experienced",
        "title": "Most Experienced",
        "description": "Highest total XP earned",
        "value_field": "experience",
    },
    {
        "id": "longest_streak",
        "title": "Longest Streak",
        "description": "Most consecutive days with commits",
        "value_field": "longest_streak",
    },
]


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(session: DbSession) -> LeaderboardResponse:
    """Return the public leaderboard with multiple categories (cached hourly)."""
    categories: list[LeaderboardCategory] = []
    now = datetime.now(UTC)

    for cat in _LEADERBOARD_CATEGORIES:
        pets = await pet_crud.get_leaderboard(session, cat["id"], limit=10)
        entries = [
            LeaderboardEntry(
                rank=i + 1,
                pet_name=p.name,
                repo_owner=p.repo_owner,
                repo_name=p.repo_name,
                stage=p.stage,
                value=getattr(p, cat["value_field"]),
            )
            for i, p in enumerate(pets)
        ]
        categories.append(
            LeaderboardCategory(
                id=cat["id"],
                title=cat["title"],
                description=cat["description"],
                entries=entries,
            )
        )

    return LeaderboardResponse(categories=categories, cached_at=now)


@router.get("/showcase/{username}.svg", response_class=Response)
async def get_showcase(
    username: str,
    session: DbSession,
    layout: str = Query(default="horizontal", pattern="^(horizontal|vertical|grid)$"),
    theme: str = Query(default="dark", pattern="^(light|dark)$"),
    max: int = Query(default=10, ge=1, le=50),
) -> Response:
    """Return an SVG showcase of all pets for a GitHub user.

    Returns a 200 with an empty-state SVG when the user has no pets.
    """
    from github_tamagotchi.services.badge import generate_showcase_svg

    pets = await pet_crud.get_pets_by_github_username(session, username, limit=max)

    pets_data = [
        {
            "name": pet.name,
            "stage": pet.stage,
            "mood": pet.mood,
            "health": pet.health,
            "is_dead": pet.is_dead,
        }
        for pet in pets
    ]

    svg_content = generate_showcase_svg(pets_data, username, layout=layout, theme=theme)

    return Response(
        content=svg_content,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=300, stale-while-revalidate=60",
            "Content-Type": "image/svg+xml; charset=utf-8",
        },
    )


@router.get("/contributor/{repo_owner}/{repo_name}/{username}.svg", response_class=Response)
async def get_contributor_badge(
    repo_owner: str,
    repo_name: str,
    username: str,
    session: DbSession,
    details: bool = Query(default=False, description="Include shame detail in badge"),
) -> Response:
    """Return an SVG badge showing a contributor's standing with the repo pet."""
    from github_tamagotchi.services.badge import ContributorStanding, generate_contributor_badge_svg
    from github_tamagotchi.services.github import ContributorStats

    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )

    # Fetch live contributor stats from GitHub
    gh = GitHubService()
    try:
        stats: ContributorStats = await gh.get_contributor_stats(repo_owner, repo_name, username)
    except Exception:
        # Fall back to a neutral badge if GitHub is unreachable
        stats = ContributorStats(
            commits_30d=0,
            last_commit_at=None,
            is_top_contributor=False,
            has_failed_ci=False,
            days_since_last_commit=None,
        )

    # Determine standing
    if stats.has_failed_ci and stats.commits_30d > 0:
        standing = ContributorStanding.DOGHOUSE
    elif stats.is_top_contributor:
        standing = ContributorStanding.FAVORITE
    elif stats.commits_30d > 0:
        standing = ContributorStanding.GOOD
    elif stats.days_since_last_commit is not None:
        standing = ContributorStanding.ABSENT
    else:
        standing = ContributorStanding.NEUTRAL

    shame_detail: str | None = None
    if details and standing == ContributorStanding.DOGHOUSE:
        days = stats.days_since_last_commit or 0
        shame_detail = f"Broke CI {days}d ago" if days else "Broke CI recently"

    svg_content = generate_contributor_badge_svg(
        pet_name=pet.name,
        pet_stage=pet.stage,
        username=username,
        standing=standing,
        score=stats.commits_30d * 10 if standing == ContributorStanding.GOOD else None,
        days_away=stats.days_since_last_commit if standing == ContributorStanding.ABSENT else None,
        shame_detail=shame_detail,
    )

    return Response(
        content=svg_content,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=300, stale-while-revalidate=60",
            "Content-Type": "image/svg+xml; charset=utf-8",
        },
    )
