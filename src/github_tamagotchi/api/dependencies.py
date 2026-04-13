"""Shared FastAPI dependency helpers for API routes."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.database import get_session
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.user import User
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.token_encryption import decrypt_token

DbSession = Annotated[AsyncSession, Depends(get_session)]


async def get_pet_or_404(repo_owner: str, repo_name: str, session: AsyncSession) -> Pet:
    """Fetch a pet by repo or raise HTTP 404."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pet not found for {repo_owner}/{repo_name}",
        )
    return pet


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
