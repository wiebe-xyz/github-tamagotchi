"""Pet CRUD endpoints: create, list, get, delete, feed, my-pets, my-repos."""

import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi.api.auth import get_current_user, get_optional_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404, validate_choice
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.schemas.pets import (
    FeedResponse,
    PetCreate,
    PetListResponse,
    PetResponse,
    RepoItem,
)
from github_tamagotchi.services import pet as pet_service
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.image_generation import STYLES
from github_tamagotchi.services.naming import generate_name_from_repo, is_valid_pet_name
from github_tamagotchi.services.token_encryption import decrypt_token

router: APIRouter = APIRouter(prefix="/api/v1", tags=["pets"])


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
    validate_choice(pet_data.style, STYLES, "style")
    if pet_data.name is None:
        pet_name = generate_name_from_repo(pet_data.repo_owner, pet_data.repo_name)
    else:
        if not is_valid_pet_name(pet_data.name):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid pet name. Use 1-20 alphanumeric chars and spaces, no profanity.",
            )
        pet_name = pet_data.name
    pet = await pet_service.create(
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
    pets, total = await pet_service.get_list(session, page=page, per_page=per_page)
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
    await pet_service.delete(session, pet)


@router.post("/pets/{repo_owner}/{repo_name}/feed", response_model=FeedResponse)
async def feed_pet(repo_owner: str, repo_name: str, session: DbSession) -> FeedResponse:
    """Manually feed the pet."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    updated_pet = await pet_service.feed(session, pet)
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
    pets, total = await pet_service.get_list(session, page=page, per_page=per_page, user_id=user.id)
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
        all_pets = await pet_service.get_all(session)
        for pet in all_pets:
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
