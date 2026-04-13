"""Pet action endpoints: resurrect."""

import math
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi import metrics as metrics_service
from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404, require_pet_owner
from github_tamagotchi.api.routes.v1.pets.crud import PetResponse
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import PetStage
from github_tamagotchi.models.user import User

router: APIRouter = APIRouter(prefix="/api/v1", tags=["pets"])


@router.post("/pets/{repo_owner}/{repo_name}/resurrect", response_model=PetResponse)
async def resurrect_pet(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetResponse:
    """Resurrect a dead pet after the mandatory 7-day mourning period."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    if not pet.is_dead:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pet is not dead and cannot be resurrected",
        )
    require_pet_owner(pet, user)
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
    pet = await pet_crud.resurrect_pet(session, pet)
    metrics_service.resurrections_total.inc()
    try:
        _api_routes.get_image_provider()
        await _api_routes.image_queue.create_job(session, pet.id, PetStage.EGG.value)
    except ValueError:
        pass
    return PetResponse.model_validate(pet)
