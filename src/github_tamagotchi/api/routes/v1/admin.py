"""Pet admin endpoints: settings, contributor exclusion, reset, delete."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select as _select
from sqlalchemy.ext.asyncio import AsyncSession

import github_tamagotchi.api.routes as _api_routes  # for test-patch-compatible symbol lookup
from github_tamagotchi.api.auth import get_current_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.user import User
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


class PetAdminSettingsUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=20)
    blame_board_enabled: bool | None = None
    contributor_badges_enabled: bool | None = None
    leaderboard_opt_out: bool | None = None
    hungry_after_days: int | None = Field(None, ge=1, le=30)
    pr_review_sla_hours: int | None = Field(None, ge=1, le=336)
    issue_response_sla_days: int | None = Field(None, ge=1, le=90)


class ExcludedContributorItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_login: str
    excluded_by: str
    excluded_at: datetime


class PetAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    blame_board_enabled: bool
    contributor_badges_enabled: bool
    leaderboard_opt_out: bool
    hungry_after_days: int
    pr_review_sla_hours: int
    issue_response_sla_days: int
    excluded_contributors: list[ExcludedContributorItem]
    is_dead: bool
    generation: int


async def _build_pet_admin_response(pet: Pet, session: AsyncSession) -> PetAdminResponse:
    from github_tamagotchi.models.excluded_contributor import ExcludedContributor

    result = await session.execute(
        _select(ExcludedContributor).where(ExcludedContributor.pet_id == pet.id)
    )
    excluded = list(result.scalars().all())
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
    if body.blame_board_enabled is not None:
        pet.blame_board_enabled = body.blame_board_enabled
    if body.contributor_badges_enabled is not None:
        pet.contributor_badges_enabled = body.contributor_badges_enabled
    if body.leaderboard_opt_out is not None:
        pet.leaderboard_opt_out = body.leaderboard_opt_out
    if body.hungry_after_days is not None:
        pet.hungry_after_days = body.hungry_after_days
    if body.pr_review_sla_hours is not None:
        pet.pr_review_sla_hours = body.pr_review_sla_hours
    if body.issue_response_sla_days is not None:
        pet.issue_response_sla_days = body.issue_response_sla_days

    await session.commit()
    await session.refresh(pet)
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
    from sqlalchemy.exc import IntegrityError

    from github_tamagotchi.models.excluded_contributor import ExcludedContributor

    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)

    entry = ExcludedContributor(
        pet_id=pet.id,
        github_login=github_login,
        excluded_by=user.github_login,
    )
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
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
    from github_tamagotchi.models.excluded_contributor import ExcludedContributor

    pet = await get_pet_or_404(repo_owner, repo_name, session)
    await _require_repo_admin(repo_owner, repo_name, user, session)

    result = await session.execute(
        _select(ExcludedContributor).where(
            ExcludedContributor.pet_id == pet.id,
            ExcludedContributor.github_login == github_login,
        )
    )
    entry = result.scalar_one_or_none()
    if entry:
        await session.delete(entry)
        await session.commit()
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
    pet = await pet_crud.reset_pet(session, pet)
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
    await pet_crud.delete_pet(session, pet)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
