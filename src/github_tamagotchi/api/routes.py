"""API routes for pet management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.database import get_session

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
    from sqlalchemy import text

    from github_tamagotchi import __version__

    try:
        await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
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
