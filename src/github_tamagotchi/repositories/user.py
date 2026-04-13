"""User repository: all User model queries with exception translation."""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.exceptions import RepositoryError
from github_tamagotchi.models.user import User
from github_tamagotchi.repositories import _commit_refresh


async def get_user_by_github_id(db: AsyncSession, github_id: int) -> User | None:
    """Get a user by their GitHub ID."""
    try:
        result = await db.execute(select(User).where(User.github_id == github_id))
        return result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """Get a user by their internal ID."""
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc


async def create_or_update_user(
    db: AsyncSession,
    *,
    github_id: int,
    github_login: str,
    github_avatar_url: str | None,
    encrypted_token: str | None,
) -> User:
    """Create a new user or update an existing one on login."""
    user = await get_user_by_github_id(db, github_id)
    if user:
        user.github_login = github_login
        user.github_avatar_url = github_avatar_url
        if encrypted_token is not None:
            user.encrypted_token = encrypted_token
    else:
        user = User(
            github_id=github_id,
            github_login=github_login,
            github_avatar_url=github_avatar_url,
            encrypted_token=encrypted_token,
        )
        db.add(user)
    await _commit_refresh(db, user)
    return user
