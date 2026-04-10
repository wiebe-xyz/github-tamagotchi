"""CRUD operations for Pet model."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood, PetSkin
from github_tamagotchi.services.pet_logic import generate_personality

# Simple in-memory leaderboard cache: stores (timestamp, data) per category
_leaderboard_cache: dict[str, tuple[datetime, list[Pet]]] = {}
_LEADERBOARD_CACHE_TTL_SECONDS = 3600  # 1 hour


async def create_pet(
    db: AsyncSession,
    repo_owner: str,
    repo_name: str,
    name: str,
    user_id: int | None = None,
    style: str = "kawaii",
) -> Pet:
    """Create a new pet with generated personality traits."""
    personality = generate_personality(repo_owner, repo_name)
    pet = Pet(
        repo_owner=repo_owner,
        repo_name=repo_name,
        name=name,
        user_id=user_id,
        style=style,
        personality_activity=personality.activity,
        personality_sociability=personality.sociability,
        personality_bravery=personality.bravery,
        personality_tidiness=personality.tidiness,
        personality_appetite=personality.appetite,
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


async def get_leaderboard(
    db: AsyncSession, category: str, limit: int = 10
) -> list[Pet]:
    """Return top pets for the given leaderboard category, with hourly caching.

    Categories:
      - "most_experienced": top by experience (XP)
      - "longest_streak": top by longest_streak
    """
    now = datetime.now(UTC)
    cache_key = f"{category}:{limit}"
    cached = _leaderboard_cache.get(cache_key)
    if cached is not None:
        cached_at, cached_data = cached
        if (now - cached_at).total_seconds() < _LEADERBOARD_CACHE_TTL_SECONDS:
            return cached_data

    base_filter = Pet.leaderboard_opt_out.is_(False), Pet.is_dead.is_(False)

    if category == "most_experienced":
        order_col = Pet.experience.desc()
    elif category == "longest_streak":
        order_col = Pet.longest_streak.desc()
    else:
        return []

    result = await db.execute(
        select(Pet).where(*base_filter).order_by(order_col).limit(limit)
    )
    pets = list(result.scalars().all())

    _leaderboard_cache[cache_key] = (now, pets)
    return pets


async def get_pets_by_github_username(
    db: AsyncSession, username: str, limit: int = 50
) -> list[Pet]:
    """Get all pets where repo_owner matches the given GitHub username, ordered by creation date."""
    result = await db.execute(
        select(Pet)
        .where(Pet.repo_owner == username)
        .order_by(Pet.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_org_pets(db: AsyncSession, org_name: str) -> list[Pet]:
    """Get all pets belonging to an org, case-insensitive, ordered by health desc."""
    from sqlalchemy import func as sqlfunc

    result = await db.execute(
        select(Pet)
        .where(sqlfunc.lower(Pet.repo_owner) == org_name.lower())
        .order_by(Pet.health.desc())
    )
    return list(result.scalars().all())


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


async def select_skin(db: AsyncSession, pet: Pet, skin: PetSkin) -> Pet:
    """Set the active skin on a pet."""
    pet.skin = skin.value
    await db.commit()
    await db.refresh(pet)
    return pet
