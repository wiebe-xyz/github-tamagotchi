"""CRUD operations for contributor relationships."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.contributor_relationship import ContributorRelationship


async def get_contributors_for_pet(
    db: AsyncSession, pet_id: int
) -> list[ContributorRelationship]:
    """Return all contributor relationships for a pet, ordered by score descending."""
    result = await db.execute(
        select(ContributorRelationship)
        .where(ContributorRelationship.pet_id == pet_id)
        .order_by(ContributorRelationship.score.desc())
    )
    return list(result.scalars().all())


async def upsert_contributor_relationship(
    db: AsyncSession,
    pet_id: int,
    github_username: str,
    score: int,
    standing: str,
    last_activity: datetime | None,
    good_deeds: list[Any],
    sins: list[Any],
) -> ContributorRelationship:
    """Insert or update a contributor relationship record."""
    result = await db.execute(
        select(ContributorRelationship).where(
            ContributorRelationship.pet_id == pet_id,
            ContributorRelationship.github_username == github_username,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.score = score
        existing.standing = standing
        existing.last_activity = last_activity
        existing.good_deeds = good_deeds
        existing.sins = sins
        return existing

    relationship = ContributorRelationship(
        pet_id=pet_id,
        github_username=github_username,
        score=score,
        standing=standing,
        last_activity=last_activity,
        good_deeds=good_deeds,
        sins=sins,
    )
    db.add(relationship)
    return relationship


async def apply_score_delta(
    db: AsyncSession,
    pet_id: int,
    github_username: str,
    delta: int,
    event_description: str,
    now: datetime | None = None,
) -> ContributorRelationship | None:
    """Apply a score delta to an existing contributor relationship.

    Used for real-time webhook updates between poll cycles.
    Returns None if the relationship does not yet exist.
    """
    from datetime import UTC

    from github_tamagotchi.models.contributor_relationship import ContributorStanding
    from github_tamagotchi.services.contributor_relationships import calculate_standing

    if now is None:
        from datetime import UTC

        now = datetime.now(UTC)

    result = await db.execute(
        select(ContributorRelationship).where(
            ContributorRelationship.pet_id == pet_id,
            ContributorRelationship.github_username == github_username,
        )
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        # Create a minimal record for this contributor
        rel = ContributorRelationship(
            pet_id=pet_id,
            github_username=github_username,
            score=0,
            standing=ContributorStanding.NEUTRAL,
            last_activity=now,
            good_deeds=[],
            sins=[],
        )
        db.add(rel)

    rel.score += delta
    rel.last_activity = now

    if delta > 0:
        deeds = list(rel.good_deeds or [])
        deeds.insert(0, event_description)
        rel.good_deeds = deeds[:5]
    else:
        sins = list(rel.sins or [])
        sins.insert(0, event_description)
        rel.sins = sins[:5]

    # Recalculate standing
    rel.standing = calculate_standing(
        score=rel.score,
        is_top_scorer=False,  # Don't recalculate top scorer during webhook; poll will fix it
        last_activity=rel.last_activity,
        now=now,
    )

    return rel
