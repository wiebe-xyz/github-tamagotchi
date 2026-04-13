"""Pet appearance endpoints: style, name, badge-style, skins."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404, require_pet_owner
from github_tamagotchi.models.pet import PetSkin
from github_tamagotchi.models.user import User
from github_tamagotchi.schemas.pets import (
    BadgeStyleUpdateRequest,
    PetRenameRequest,
    PetResponse,
    SkinInfo,
    SkinSelectRequest,
    SkinSelectResponse,
    StyleUpdateRequest,
)
from github_tamagotchi.services import pet as pet_service
from github_tamagotchi.services.badge import BADGE_STYLES
from github_tamagotchi.services.image_generation import STYLES
from github_tamagotchi.services.naming import is_valid_pet_name
from github_tamagotchi.services.pet_logic import SKIN_UNLOCK_CONDITIONS, get_unlocked_skins

router: APIRouter = APIRouter(prefix="/api/v1", tags=["pets"])


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
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    require_pet_owner(pet, user)
    pet = await pet_service.update_style(session, pet, style_data.style)
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
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    require_pet_owner(pet, user)
    pet = await pet_service.rename(session, pet, rename_data.name)
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
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    require_pet_owner(pet, user)
    pet = await pet_service.update_badge_style(session, pet, badge_style_data.badge_style)
    return PetResponse.model_validate(pet)


@router.get("/pets/{repo_owner}/{repo_name}/skins", response_model=list[SkinInfo])
async def list_skins(repo_owner: str, repo_name: str, session: DbSession) -> list[SkinInfo]:
    """List all skins and their unlock status for a pet."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
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
    pet = await get_pet_or_404(repo_owner, repo_name, session)
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
    updated_pet = await pet_service.select_skin(session, pet, chosen_skin)
    return SkinSelectResponse(
        message=f"{updated_pet.name} is now wearing the {chosen_skin.value} skin!",
        pet=PetResponse.model_validate(updated_pet),
    )
