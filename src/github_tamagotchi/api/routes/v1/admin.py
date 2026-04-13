"""Pet admin endpoints: settings, contributor exclusion, reset, delete."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.user import User
from github_tamagotchi.schemas.admin import (
    ExcludedContributorItem,
    PetAdminResponse,
    PetAdminSettingsUpdate,
)
from github_tamagotchi.services import pet as pet_service
from github_tamagotchi.services.naming import is_valid_pet_name

router: APIRouter = APIRouter(prefix="/api/v1", tags=["admin"])


async def _require_repo_admin(
    repo_owner: str,
    repo_name: str,
    user: User,
    session: AsyncSession,
) -> None:
    """Raise 403 if the current user is not an admin of the given repo.

    Uses _api_routes.decrypt_token and _api_routes.GitHubService so that
    tests patching github_tamagotchi.api.routes.decrypt_token / GitHubService
    affect this function.
    """
    if user.is_admin:
        return
    if not user.encrypted_token:
        raise HTTPException(
            status_code=403, detail="No GitHub token available to verify repo access"
        )
    token = _api_routes.decrypt_token(user.encrypted_token)
    gh = _api_routes.GitHubService(token=token)
    try:
        permission = await gh.get_repo_permission(repo_owner, repo_name, user.github_login)
    except Exception as exc:
        raise HTTPException(
            status_code=403, detail="Unable to verify repo admin permission"
        ) from exc
    if permission != "admin":
        raise HTTPException(status_code=403, detail="Repo admin permission required")


async def _build_pet_admin_response(pet: Pet, session: AsyncSession) -> PetAdminResponse:
    from github_tamagotchi.repositories.excluded_contributor import get_excluded_for_pet

    excluded = await get_excluded_for_pet(session, pet.id)
    return PetAdminResponse(
        id=pet.id,
        name=pet.name,
        blame_board_enabled=pet.blame_board_enabled,
        contributor_badges_enabled=pet.contributor_badges_enabled,
        leaderboard_opt_out=pet.leaderboard_opt_out,
        hungry_after_days=pet.hungry_after_days,
        pr_review_sla_hours=pet.pr_review_sla_hours,
        issue_response_sla_days=pet.issue_response_sla_days,
        excluded_contributors=[ExcludedContributorItem.model_validate(e) for e in excluded],
        is_dead=pet.is_dead,
        generation=pet.generation,
    )


@router.get("/pets/{repo_owner}/{repo_name}/admin", response_model=PetAdminResponse)
async def get_pet_admin(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetAdminResponse:
    """Get pet admin settings. Requires repo admin permission."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)
    return await _build_pet_admin_response(pet, session)


@router.patch("/pets/{repo_owner}/{repo_name}/admin/settings", response_model=PetAdminResponse)
async def update_pet_admin_settings(
    repo_owner: str,
    repo_name: str,
    body: PetAdminSettingsUpdate,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetAdminResponse:
    """Update pet admin settings. Requires repo admin permission."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)

    if body.name is not None:
        if not is_valid_pet_name(body.name):
            raise HTTPException(status_code=422, detail="Invalid pet name")
        pet.name = body.name
    for field, value in body.model_dump(exclude_unset=True, exclude={"name"}).items():
        setattr(pet, field, value)

    pet = await pet_service.save(session, pet)
    return await _build_pet_admin_response(pet, session)


@router.post(
    "/pets/{repo_owner}/{repo_name}/admin/contributors/exclude",
    status_code=status.HTTP_201_CREATED,
)
async def exclude_contributor(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    github_login: str = Query(..., min_length=1, max_length=255),
) -> dict[str, str]:
    """Exclude a contributor from this pet's tracking. Requires repo admin permission."""
    from github_tamagotchi.repositories.excluded_contributor import add_excluded

    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)
    await add_excluded(session, pet.id, github_login, user.github_login)
    return {"status": "excluded", "github_login": github_login}


@router.delete(
    "/pets/{repo_owner}/{repo_name}/admin/contributors/{github_login}/exclude",
    response_model=dict,
)
async def unexclude_contributor(
    repo_owner: str,
    repo_name: str,
    github_login: str,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """Remove contributor exclusion. Requires repo admin permission."""
    from github_tamagotchi.repositories.excluded_contributor import remove_excluded

    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)
    await remove_excluded(session, pet.id, github_login)
    return {"status": "unexcluded", "github_login": github_login}


@router.post("/pets/{repo_owner}/{repo_name}/admin/reset", response_model=PetAdminResponse)
async def reset_pet(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> PetAdminResponse:
    """Reset pet stats and start a new generation. Requires repo admin permission."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)
    pet = await pet_service.reset(session, pet)
    return await _build_pet_admin_response(pet, session)


@router.delete("/pets/{repo_owner}/{repo_name}/admin", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pet_admin(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Delete a pet entirely. Requires repo admin permission."""
    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)
    await pet_service.delete(session, pet)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
