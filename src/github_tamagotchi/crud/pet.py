"""CRUD operations for Pet model."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood


async def create_pet(db: AsyncSession, repo_owner: str, repo_name: str, name: str) -> Pet:
    """Create a new pet."""
    pet = Pet(
        repo_owner=repo_owner,
        repo_name=repo_name,
        name=name,
    )
    db.add(pet)
    await db.commit()
    await db.refresh(pet)
    return pet


async def get_pet_by_repo(db: AsyncSession, owner: str, repo: str) -> Pet | None:
    """Get a pet by repository owner and name."""
    result = await db.execute(select(Pet).where(Pet.repo_owner == owner, Pet.repo_name == repo))
    return result.scalar_one_or_none()


async def get_pets(db: AsyncSession, page: int = 1, per_page: int = 10) -> tuple[list[Pet], int]:
    """Get all pets with pagination."""
    offset = (page - 1) * per_page

    count_result = await db.execute(select(func.count()).select_from(Pet))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Pet).order_by(Pet.created_at.desc()).offset(offset).limit(per_page)
    )
    pets = list(result.scalars().all())

    return pets, total


async def delete_pet(db: AsyncSession, pet: Pet) -> None:
    """Delete a pet."""
    await db.delete(pet)
    await db.commit()


async def feed_pet(db: AsyncSession, pet: Pet) -> Pet:
    """Feed a pet to improve its health and mood."""
    pet.health = min(100, pet.health + 10)
    pet.last_fed_at = datetime.now(UTC)

    if pet.health >= 80:
        pet.mood = PetMood.HAPPY.value
    elif pet.health >= 50:
        pet.mood = PetMood.CONTENT.value

    await db.commit()
    await db.refresh(pet)
    return pet
