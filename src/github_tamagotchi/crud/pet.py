"""CRUD operations for Pet model."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood


async def create_pet(
    db: AsyncSession,
    repo_owner: str,
    repo_name: str,
    name: str,
    user_id: int | None = None,
    style: str = "kawaii",
) -> Pet:
    """Create a new pet."""
    pet = Pet(
        repo_owner=repo_owner,
        repo_name=repo_name,
        name=name,
        user_id=user_id,
        style=style,
    )
    db.add(pet)
    await db.commit()
    await db.refresh(pet)
    return pet


async def get_pet_by_repo(db: AsyncSession, owner: str, repo: str) -> Pet | None:
    """Get a pet by repository owner and name."""
    result = await db.execute(select(Pet).where(Pet.repo_owner == owner, Pet.repo_name == repo))
    return result.scalar_one_or_none()


async def get_pets(
    db: AsyncSession, page: int = 1, per_page: int = 10, user_id: int | None = None
) -> tuple[list[Pet], int]:
    """Get pets with pagination, optionally filtered by user."""
    offset = (page - 1) * per_page

    base_query = select(Pet)
    count_query = select(func.count()).select_from(Pet)
    if user_id is not None:
        base_query = base_query.where(Pet.user_id == user_id)
        count_query = count_query.where(Pet.user_id == user_id)

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    result = await db.execute(
        base_query.order_by(Pet.created_at.desc()).offset(offset).limit(per_page)
    )
    pets = list(result.scalars().all())

    return pets, total


async def get_pets_with_owners(
    db: AsyncSession, page: int = 1, per_page: int = 20
) -> tuple[list[dict[str, object]], int]:
    """Get all pets with their owner info, paginated."""
    from github_tamagotchi.models.user import User

    offset = (page - 1) * per_page

    count_result = await db.execute(select(func.count()).select_from(Pet))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Pet, User)
        .outerjoin(User, Pet.user_id == User.id)
        .order_by(Pet.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    rows = [{"pet": row.Pet, "owner": row.User} for row in result]
    return rows, total


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
