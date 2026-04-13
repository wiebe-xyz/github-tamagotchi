"""Pet appearance endpoints: style, name, badge-style, skins."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.api.dependencies import DbSession
from github_tamagotchi.api.routes.v1.pets.crud import PetResponse
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import PetSkin
from github_tamagotchi.models.user import User
from github_tamagotchi.services.badge import BADGE_STYLES
from github_tamagotchi.services.image_generation import STYLES
from github_tamagotchi.services.naming import is_valid_pet_name
from github_tamagotchi.services.pet_logic import SKIN_UNLOCK_CONDITIONS, get_unlocked_skins

router = APIRouter(prefix="/api/v1", tags=["pets"])


class StyleUpdateRequest(BaseModel):
    style: str = Field(..., min_length=1, max_length=30)


class PetRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)


class BadgeStyleUpdateRequest(BaseModel):
    badge_style: str = Field(..., min_length=1, max_length=20)


class SkinInfo(BaseModel):
    skin: str
    unlocked: bool
    unlock_condition: str


class SkinSelectRequest(BaseModel):
    skin: str = Field(..., min_length=1, max_length=20)


class SkinSelectResponse(BaseModel):
    message: str
    pet: PetResponse


@router.put("/pets/{repo_owner}/{repo_name}/style", response_model=PetResponse)
async def update_pet_style(
    repo_owner: str,
    repo_name: str,
    style_data: StyleUpdateRequest,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetResponse:
    """Update a pet's style and enqueue image regeneration."""
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
    if pet.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this pet")
    pet.style = style_data.style
    await session.commit()
    await session.refresh(pet)
    try:
        _api_routes.get_image_provider()
        await _api_routes.image_queue.create_job(session, pet.id, pet.stage)
    except ValueError:
        pass
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this pet")
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this pet")
    pet.badge_style = badge_style_data.badge_style
    await session.commit()
    await session.refresh(pet)
    return PetResponse.model_validate(pet)


@router.get("/pets/{repo_owner}/{repo_name}/skins", response_model=list[SkinInfo])
async def list_skins(repo_owner: str, repo_name: str, session: DbSession) -> list[SkinInfo]:
    """List all skins and their unlock status for a pet."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    unlocked = get_unlocked_skins(pet)
    return [
        SkinInfo(
            skin=skin.value,
            unlocked=skin in unlocked,
            unlock_condition=SKIN_UNLOCK_CONDITIONS[skin],
        )
        for skin in PetSkin
    ]


@router.put("/pets/{repo_owner}/{repo_name}/skin", response_model=SkinSelectResponse)
async def select_skin(
    repo_owner: str, repo_name: str, body: SkinSelectRequest, session: DbSession
) -> SkinSelectResponse:
    """Set the active skin for a pet (must be unlocked)."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    try:
        chosen_skin = PetSkin(body.skin)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown skin '{body.skin}'",
        ) from exc
    unlocked = get_unlocked_skins(pet)
    if chosen_skin not in unlocked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Skin '{body.skin}' is not yet unlocked for this pet",
        )
    updated_pet = await pet_crud.select_skin(session, pet, chosen_skin)
    return SkinSelectResponse(
        message=f"{updated_pet.name} is now wearing the {chosen_skin.value} skin!",
        pet=PetResponse.model_validate(updated_pet),
    )
