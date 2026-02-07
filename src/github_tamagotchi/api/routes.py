"""API routes for pet management."""

import logging
import math
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import get_session
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.services.webhook import EVENT_HANDLERS, verify_signature

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

    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_owner: str
    repo_name: str
    name: str
    stage: str
    mood: str
    health: int
    experience: int
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


class ComfyUIHealthResponse(BaseModel):
    """ComfyUI health check response."""

    available: bool
    queue_remaining: int | None = None
    cuda_available: bool | None = None


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
    health_status = await service.check_health()
    return ComfyUIHealthResponse(
        available=health_status.available,
        queue_remaining=health_status.queue_remaining,
        cuda_available=health_status.cuda_available,
    )


@router.post("/pets", response_model=PetResponse, status_code=status.HTTP_201_CREATED)
async def create_pet(pet_data: PetCreate, session: DbSession) -> PetResponse:
    """Create a new pet for a GitHub repository."""
    existing = await pet_crud.get_pet_by_repo(session, pet_data.repo_owner, pet_data.repo_name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pet already exists for {pet_data.repo_owner}/{pet_data.repo_name}",
        )
    pet = await pet_crud.create_pet(session, pet_data.repo_owner, pet_data.repo_name, pet_data.name)
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


@router.post("/webhooks/github", response_model=WebhookResponse)
async def github_webhook(request: Request, session: DbSession) -> WebhookResponse:
    """Receive GitHub webhook events and update pet state."""
    body = await request.body()

    # Verify signature if webhook secret is configured
    if settings.github_webhook_secret:
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not signature or not verify_signature(
            body, signature, settings.github_webhook_secret
        ):
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
    message = await handler(payload, session)
    return WebhookResponse(status="processed", message=message)
