"""Shared FastAPI dependency helpers for API routes."""

from collections.abc import Mapping
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.user import User
from github_tamagotchi.services import pet as pet_service
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.token_encryption import decrypt_token

DbSession = Annotated[AsyncSession, Depends(get_session)]


def validate_choice(value: str, allowed: Mapping[str, object] | set[str], field_name: str) -> None:
    """Raise HTTP 422 if *value* is not in *allowed*."""
    if value not in allowed:
        valid = ", ".join(sorted(allowed.keys() if isinstance(allowed, Mapping) else allowed))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {field_name} '{value}'. Must be one of: {valid}",
        )


async def get_pet_or_404(repo_owner: str, repo_name: str, session: AsyncSession) -> Pet:
    """Fetch a pet by repo or raise NotFoundError (→ HTTP 404 via exception handler)."""
    return await pet_service.get_or_raise(session, repo_owner, repo_name)


def require_pet_owner(pet: Pet, user: User) -> None:
    """Raise HTTP 403 if the user does not own the pet (site admins are exempt)."""
    if pet.user_id != user.id and not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this pet"
        )


async def require_repo_admin(
    repo_owner: str,
    repo_name: str,
    user: User,
    session: AsyncSession,
) -> None:
    """Raise HTTP 403 if the current user does not have admin rights on the repo.

    Site-wide admins bypass the GitHub permission check.
    """
    if user.is_admin:
        return

    if not user.encrypted_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No GitHub token available to verify repo access",
        )

    token = decrypt_token(user.encrypted_token)
    gh = GitHubService(token=token)
    try:
        permission = await gh.get_repo_permission(repo_owner, repo_name, user.github_login)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unable to verify repo admin permission",
        ) from exc

    if permission != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Repo admin permission required",
        )
