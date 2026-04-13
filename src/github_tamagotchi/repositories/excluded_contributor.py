"""ExcludedContributor repository: queries with exception translation."""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.exceptions import RepositoryError
from github_tamagotchi.models.excluded_contributor import ExcludedContributor
from github_tamagotchi.repositories import _commit_refresh


async def get_excluded_for_pet(db: AsyncSession, pet_id: int) -> list[ExcludedContributor]:
    """Return all excluded contributors for a pet."""
    try:
        result = await db.execute(
            select(ExcludedContributor).where(ExcludedContributor.pet_id == pet_id)
        )
        return list(result.scalars().all())
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc


async def add_excluded(
    db: AsyncSession, pet_id: int, github_login: str, excluded_by: str
) -> None:
    """Exclude a contributor from pet tracking. Silently ignores duplicates."""
    from sqlalchemy.exc import IntegrityError

    entry = ExcludedContributor(pet_id=pet_id, github_login=github_login, excluded_by=excluded_by)
    db.add(entry)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()


async def remove_excluded(db: AsyncSession, pet_id: int, github_login: str) -> None:
    """Remove an exclusion entry if it exists."""
    try:
        result = await db.execute(
            select(ExcludedContributor).where(
                ExcludedContributor.pet_id == pet_id,
                ExcludedContributor.github_login == github_login,
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            await db.delete(entry)
            await _commit_refresh(db)
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc
