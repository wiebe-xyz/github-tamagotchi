"""Pet domain service.

All business operations on pets flow through here.
Routes call this module; this module calls repositories.
"""

import math
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.exceptions import ConflictError, NotFoundError
from github_tamagotchi.models.pet import Pet, PetSkin
from github_tamagotchi.repositories import pet as pet_repo

_tracer = get_tracer(__name__)


async def get_or_raise(db: AsyncSession, owner: str, repo: str) -> Pet:
    """Return the pet for a repo, or raise NotFoundError."""
    with _tracer.start_as_current_span(
        "service.pet.get_or_raise",
        attributes={"pet.owner": owner, "pet.repo": repo},
    ):
        pet = await pet_repo.get_pet_by_repo(db, owner, repo)
        if pet is None:
            raise NotFoundError(f"Pet not found for {owner}/{repo}")
        return pet


async def get_by_repo(db: AsyncSession, owner: str, repo: str) -> Pet | None:
    return await pet_repo.get_pet_by_repo(db, owner, repo)


async def get_list(
    db: AsyncSession, page: int, per_page: int, user_id: int | None = None
) -> tuple[list[Pet], int]:
    with _tracer.start_as_current_span(
        "service.pet.get_list",
        attributes={"page": page, "per_page": per_page},
    ) as span:
        pets, total = await pet_repo.get_pets(
            db, page=page, per_page=per_page, user_id=user_id
        )
        span.set_attribute("result.count", len(pets))
        span.set_attribute("result.total", total)
        return pets, total


async def get_leaderboard(db: AsyncSession, category: str, limit: int = 10) -> list[Pet]:
    return await pet_repo.get_leaderboard(db, category, limit=limit)


async def get_by_username(db: AsyncSession, username: str, limit: int = 50) -> list[Pet]:
    return await pet_repo.get_pets_by_github_username(db, username, limit=limit)


async def create(
    db: AsyncSession,
    owner: str,
    repo: str,
    name: str,
    user_id: int | None,
    style: str,
) -> Pet:
    """Create a pet, raising ConflictError if one already exists for the repo."""
    with _tracer.start_as_current_span(
        "service.pet.create",
        attributes={
            "pet.owner": owner,
            "pet.repo": repo,
            "pet.name": name,
            "pet.style": style,
        },
    ):
        existing = await pet_repo.get_pet_by_repo(db, owner, repo)
        if existing:
            raise ConflictError(f"Pet already exists for {owner}/{repo}")
        return await pet_repo.create_pet(
            db, owner, repo, name, user_id=user_id, style=style
        )


async def delete(db: AsyncSession, pet: Pet) -> None:
    await pet_repo.delete_pet(db, pet)


async def feed(db: AsyncSession, pet: Pet) -> Pet:
    return await pet_repo.feed_pet(db, pet)


async def select_skin(db: AsyncSession, pet: Pet, skin: PetSkin) -> Pet:
    return await pet_repo.select_skin(db, pet, skin)


async def update_style(db: AsyncSession, pet: Pet, style: str) -> Pet:
    pet.style = style
    return await pet_repo.save(db, pet)


async def rename(db: AsyncSession, pet: Pet, name: str) -> Pet:
    pet.name = name
    return await pet_repo.save(db, pet)


async def update_badge_style(db: AsyncSession, pet: Pet, badge_style: str) -> Pet:
    pet.badge_style = badge_style
    return await pet_repo.save(db, pet)


async def resurrect(db: AsyncSession, pet: Pet) -> Pet:
    """Validate mourning period has elapsed, then resurrect the pet.

    Raises ValueError if the pet is not dead or the mourning period has not elapsed.
    Raises NotFoundError (via get_or_raise) if the pet doesn't exist.
    """
    with _tracer.start_as_current_span(
        "service.pet.resurrect",
        attributes={"pet.id": pet.id, "pet.is_dead": pet.is_dead},
    ):
        if not pet.is_dead:
            raise ValueError("Pet is not dead and cannot be resurrected")
        if pet.died_at is None:
            raise ValueError("Pet death timestamp is missing")
        now = datetime.now(UTC)
        died_at = pet.died_at
        if died_at.tzinfo is None:
            died_at = died_at.replace(tzinfo=UTC)
        days_elapsed = (now - died_at).total_seconds() / 86400
        mourning_days = 7
        if days_elapsed < mourning_days:
            days_remaining = math.ceil(mourning_days - days_elapsed)
            day_word = "day" if days_remaining == 1 else "days"
            raise ValueError(
                f"Your pet must rest for {days_remaining} more "
                f"{day_word} before resurrection"
            )
        return await pet_repo.resurrect_pet(db, pet)


async def reset(db: AsyncSession, pet: Pet) -> Pet:
    return await pet_repo.reset_pet(db, pet)


async def update_images_generated_at(db: AsyncSession, owner: str, repo: str) -> None:
    await pet_repo.update_images_generated_at(db, owner, repo)


async def update_canonical_appearance(
    db: AsyncSession, owner: str, repo: str, appearance: str
) -> None:
    await pet_repo.update_canonical_appearance(db, owner, repo, appearance)


async def save(db: AsyncSession, pet: Pet) -> Pet:
    return await pet_repo.save(db, pet)


async def get_all(db: AsyncSession, limit: int = 10000) -> list[Pet]:
    with _tracer.start_as_current_span(
        "service.pet.get_all",
        attributes={"limit": limit},
    ) as span:
        pets = await pet_repo.get_all(db, limit=limit)
        span.set_attribute("result.count", len(pets))
        return pets
