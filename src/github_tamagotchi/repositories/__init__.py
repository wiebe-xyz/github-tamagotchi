"""Data access layer. All SQLAlchemy queries live here."""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.exceptions import ConflictError, RepositoryError


async def _commit_refresh(db: AsyncSession, *objects: object) -> None:
    """Commit the session and refresh any given objects.

    Translates IntegrityError → ConflictError and SQLAlchemyError → RepositoryError
    so callers never see raw SQLAlchemy exceptions.
    """
    try:
        await db.commit()
        for obj in objects:
            await db.refresh(obj)
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(str(exc)) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise RepositoryError(str(exc)) from exc
