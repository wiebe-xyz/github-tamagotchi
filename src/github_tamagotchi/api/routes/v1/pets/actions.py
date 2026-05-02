"""Pet action endpoints: resurrect."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi import metrics as metrics_service
from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404, require_pet_owner
from github_tamagotchi.models.pet import PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.schemas.pets import PetResponse
from github_tamagotchi.services import pet as pet_service

logger = structlog.get_logger()
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
    require_pet_owner(pet, user)
    try:
        pet = await pet_service.resurrect(session, pet)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    metrics_service.resurrections_total.inc()
    try:
        _api_routes.get_image_provider()
        await _api_routes.image_queue.create_job(session, pet.id, PetStage.EGG.value)
    except ValueError:
        logger.debug("image_enqueue_skipped", pet_id=pet.id, reason="no image provider")
    return PetResponse.model_validate(pet)
