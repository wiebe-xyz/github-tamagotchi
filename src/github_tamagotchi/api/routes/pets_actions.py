"""Pet action endpoints: resurrect."""

import math
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi import metrics as metrics_service
from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.api.dependencies import DbSession
from github_tamagotchi.api.routes.pets_crud import PetResponse
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.models.user import User

router = APIRouter(prefix="/api/v1", tags=["pets"])


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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this pet")
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
    pet.is_dead = False
    pet.died_at = None
    pet.cause_of_death = None
    pet.grace_period_started = None
    pet.stage = PetStage.EGG.value
    pet.health = 60
    pet.experience = 0
    pet.mood = PetMood.CONTENT.value
    pet.generation += 1
    metrics_service.resurrections_total.inc()
    await session.commit()
    await session.refresh(pet)
    try:
        _api_routes.get_image_provider()
        await _api_routes.image_queue.create_job(session, pet.id, PetStage.EGG.value)
    except ValueError:
        pass
    return PetResponse.model_validate(pet)
