"""Pet CRUD endpoints: create, list, get, delete, feed, my-pets, my-repos."""

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select as sa_select

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi.api.auth import get_current_user, get_optional_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.image_generation import DEFAULT_STYLE, STYLES
from github_tamagotchi.services.naming import generate_name_from_repo, is_valid_pet_name
from github_tamagotchi.services.token_encryption import decrypt_token

router: APIRouter = APIRouter(prefix="/api/v1", tags=["pets"])


class PetCreate(BaseModel):
    repo_owner: str = Field(..., min_length=1, max_length=255)
    repo_name: str = Field(..., min_length=1, max_length=255)
    name: str | None = Field(None, min_length=1, max_length=20)
    style: str = Field(DEFAULT_STYLE, min_length=1, max_length=30)


class PetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_owner: str
    repo_name: str
    name: str
    stage: str
    mood: str
    health: int
    experience: int
    skin: str
    low_health_recoveries: int
    style: str
    badge_style: str
    commit_streak: int
    longest_streak: int
    generation: int
    is_dead: bool
    died_at: object | None
    cause_of_death: str | None
    personality_activity: float | None
    personality_sociability: float | None
    personality_bravery: float | None
    personality_tidiness: float | None
    personality_appetite: float | None
    created_at: object
    updated_at: object
    last_fed_at: object | None
    last_checked_at: object | None
    dependent_count: int
    grace_period_started: object | None


class PetListResponse(BaseModel):
    items: list[PetResponse]
    total: int
    page: int
    per_page: int
    pages: int


class FeedResponse(BaseModel):
    message: str
    pet: PetResponse


class RepoItem(BaseModel):
    full_name: str
    owner: str
    name: str
    description: str | None
    private: bool
    has_pet: bool
    pet_name: str | None


def _build_pet_list_response(
    pets: list[Pet], total: int, page: int, per_page: int
) -> PetListResponse:
    pages = math.ceil(total / per_page) if total > 0 else 1
    return PetListResponse(
        items=[PetResponse.model_validate(p) for p in pets],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


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
    try:
        _api_routes.get_image_provider()
        await _api_routes.image_queue.create_job(session, pet.id, PetStage.EGG.value)
    except ValueError:
        pass
    return PetResponse.model_validate(pet)


@router.get("/pets", response_model=PetListResponse)
async def list_pets(
    session: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 10,
) -> PetListResponse:
    """List all pets with pagination."""
    pets, total = await pet_crud.get_pets(session, page=page, per_page=per_page)
    return _build_pet_list_response(pets, total, page, per_page)


@router.get("/pets/{repo_owner}/{repo_name}", response_model=PetResponse)
async def get_pet(repo_owner: str, repo_name: str, session: DbSession) -> PetResponse:
    """Get pet status for a repository."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    return PetResponse.model_validate(pet)


@router.delete("/pets/{repo_owner}/{repo_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pet(repo_owner: str, repo_name: str, session: DbSession) -> None:
    """Delete a pet."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await pet_crud.delete_pet(session, pet)


@router.post("/pets/{repo_owner}/{repo_name}/feed", response_model=FeedResponse)
async def feed_pet(repo_owner: str, repo_name: str, session: DbSession) -> FeedResponse:
    """Manually feed the pet."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    updated_pet = await pet_crud.feed_pet(session, pet)
    return FeedResponse(
        message=f"{updated_pet.name} has been fed!",
        pet=PetResponse.model_validate(updated_pet),
    )


@router.get("/me/pets", response_model=PetListResponse)
async def list_my_pets(
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 10,
) -> PetListResponse:
    """List pets belonging to the authenticated user."""
    pets, total = await pet_crud.get_pets(session, page=page, per_page=per_page, user_id=user.id)
    return _build_pet_list_response(pets, total, page, per_page)


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
    writable = [r for r in raw_repos if r.get("permissions", {}).get("push")]

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
