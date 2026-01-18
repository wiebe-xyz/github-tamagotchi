"""API routes for pet management."""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Pet, PetMood, PetStage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["pets"])

DbSession = Annotated[AsyncSession, Depends(get_session)]


class PetCreate(BaseModel):
    """Request model for creating a pet."""

    repo_owner: str = Field(..., min_length=1, max_length=255)
    repo_name: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=100)


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


class PetListResponse(BaseModel):
    """Response model for paginated pet list."""

    items: list[PetResponse]
    total: int
    page: int
    page_size: int
    pages: int


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str


class ComfyUIHealthResponse(BaseModel):
    """ComfyUI health check response."""

    available: bool
    queue_remaining: int | None = None
    cuda_available: bool | None = None


def _pet_to_response(pet: Pet) -> PetResponse:
    """Convert a Pet model to PetResponse."""
    return PetResponse(
        id=pet.id,
        repo_owner=pet.repo_owner,
        repo_name=pet.repo_name,
        name=pet.name,
        stage=pet.stage,
        mood=pet.mood,
        health=pet.health,
        experience=pet.experience,
    )


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


@router.get("/health/comfyui", response_model=ComfyUIHealthResponse)
async def comfyui_health_check() -> ComfyUIHealthResponse:
    """Check ComfyUI availability."""
    from github_tamagotchi.services.comfyui import ComfyUIService

    service = ComfyUIService()
    status = await service.check_health()
    return ComfyUIHealthResponse(
        available=status.available,
        queue_remaining=status.queue_remaining,
        cuda_available=status.cuda_available,
    )


@router.post("/pets", response_model=PetResponse, status_code=201)
async def create_pet(pet_data: PetCreate, session: DbSession) -> PetResponse:
    """Create a new pet for a GitHub repository."""
    pet = Pet(
        repo_owner=pet_data.repo_owner,
        repo_name=pet_data.repo_name,
        name=pet_data.name,
        stage=PetStage.EGG.value,
        mood=PetMood.CONTENT.value,
        health=100,
        experience=0,
    )
    session.add(pet)
    try:
        await session.commit()
        await session.refresh(pet)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Pet for repository {pet_data.repo_owner}/{pet_data.repo_name} already exists",
        ) from None
    return _pet_to_response(pet)


@router.get("/pets", response_model=PetListResponse)
async def list_pets(
    session: DbSession,
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=100, description="Items per page"),
) -> PetListResponse:
    """List all pets with pagination."""
    # Count total pets
    count_stmt = select(func.count(Pet.id))
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Calculate pagination
    offset = (page - 1) * page_size
    pages = (total + page_size - 1) // page_size if total > 0 else 1

    # Get paginated pets
    stmt = select(Pet).offset(offset).limit(page_size).order_by(Pet.id)
    result = await session.execute(stmt)
    pets = result.scalars().all()

    return PetListResponse(
        items=[_pet_to_response(pet) for pet in pets],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/pets/{repo_owner}/{repo_name}", response_model=PetResponse)
async def get_pet(repo_owner: str, repo_name: str, session: DbSession) -> PetResponse:
    """Get pet status for a repository."""
    stmt = select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
    result = await session.execute(stmt)
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pet for repository {repo_owner}/{repo_name} not found",
        )
    return _pet_to_response(pet)


@router.post("/pets/{repo_owner}/{repo_name}/feed", response_model=PetResponse)
async def feed_pet(repo_owner: str, repo_name: str, session: DbSession) -> PetResponse:
    """Manually feed the pet (triggered by activity)."""
    stmt = select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
    result = await session.execute(stmt)
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pet for repository {repo_owner}/{repo_name} not found",
        )

    # Feeding increases health and sets mood to happy
    pet.health = min(100, pet.health + 10)
    pet.mood = PetMood.HAPPY.value
    pet.last_fed_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(pet)
    return _pet_to_response(pet)


@router.delete("/pets/{repo_owner}/{repo_name}", status_code=204)
async def delete_pet(repo_owner: str, repo_name: str, session: DbSession) -> None:
    """Remove a pet from the system."""
    stmt = select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
    result = await session.execute(stmt)
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(
            status_code=404,
            detail=f"Pet for repository {repo_owner}/{repo_name} not found",
        )

    await session.delete(pet)
    await session.commit()
