"""Milestone repository: all PetMilestone model queries with exception translation."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.exceptions import ConflictError, RepositoryError
from github_tamagotchi.models.milestone import PetMilestone
from github_tamagotchi.models.pet import Pet


async def create_milestone(
    db: AsyncSession,
    pet: Pet,
    old_stage: str,
    new_stage: str,
    experience: int,
) -> PetMilestone:
    """Record an evolution milestone for a pet."""
    now = datetime.now(UTC)
    created_at = pet.created_at
    # Normalise to UTC-aware for subtraction
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max(0, int((now - created_at).total_seconds() / 86400))

    milestone = PetMilestone(
        pet_id=pet.id,
        old_stage=old_stage,
        new_stage=new_stage,
        experience=experience,
        age_days=age_days,
    )
    try:
        db.add(milestone)
        # Caller is responsible for commit
        return milestone
    except IntegrityError as exc:
        raise ConflictError(str(exc)) from exc
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc


async def get_latest_milestone(db: AsyncSession, pet_id: int) -> PetMilestone | None:
    """Return the most recent evolution milestone for a pet, if any."""
    try:
        result = await db.execute(
            select(PetMilestone)
            .where(PetMilestone.pet_id == pet_id)
            .order_by(PetMilestone.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc


async def get_milestones(db: AsyncSession, pet_id: int, limit: int = 10) -> list[PetMilestone]:
    """Return recent evolution milestones for a pet, newest first."""
    try:
        result = await db.execute(
            select(PetMilestone)
            .where(PetMilestone.pet_id == pet_id)
            .order_by(PetMilestone.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
    except SQLAlchemyError as exc:
        raise RepositoryError(str(exc)) from exc
