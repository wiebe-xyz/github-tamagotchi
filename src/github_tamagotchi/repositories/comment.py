"""Comment repository: PetComment queries with exception translation."""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.exceptions import RepositoryError
from github_tamagotchi.models.comment import PetComment
from github_tamagotchi.repositories import _commit_refresh


async def get_comments_for_pet(
    db: AsyncSession, repo_owner: str, repo_name: str, limit: int = 50
) -> list[PetComment]:
    """Return the newest comments for a pet, newest first."""
    try:
        result = await db.execute(
            select(PetComment)
            .where(PetComment.repo_owner == repo_owner, PetComment.repo_name == repo_name)
            .order_by(PetComment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc


async def create_comment(
    db: AsyncSession,
    repo_owner: str,
    repo_name: str,
    user_id: int,
    author_name: str,
    body: str,
) -> PetComment:
    """Insert a new comment and return it."""
    comment = PetComment(
        repo_owner=repo_owner,
        repo_name=repo_name,
        user_id=user_id,
        author_name=author_name,
        body=body,
    )
    db.add(comment)
    await _commit_refresh(db, comment)
    return comment
