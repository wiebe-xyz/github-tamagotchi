"""Unit tests for Pet CRUD operations."""

from datetime import UTC, datetime

from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import Pet, PetMood


async def test_create_pet(test_db: AsyncSession) -> None:
    """Test creating a new pet."""
    pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Fluffy")

    assert pet.id is not None
    assert pet.repo_owner == "testuser"
    assert pet.repo_name == "testrepo"
    assert pet.name == "Fluffy"
    assert pet.stage == "egg"
    assert pet.mood == "content"
    assert pet.health == 100
    assert pet.experience == 0


async def test_get_pet_by_repo(test_db: AsyncSession) -> None:
    """Test getting a pet by repository."""
    await pet_crud.create_pet(test_db, "testuser", "testrepo", "Fluffy")

    pet = await pet_crud.get_pet_by_repo(test_db, "testuser", "testrepo")

    assert pet is not None
    assert pet.name == "Fluffy"


async def test_get_pet_by_repo_not_found(test_db: AsyncSession) -> None:
    """Test getting a non-existent pet."""
    pet = await pet_crud.get_pet_by_repo(test_db, "nobody", "nowhere")
    assert pet is None


async def test_get_pets_empty(test_db: AsyncSession) -> None:
    """Test listing pets when none exist."""
    pets, total = await pet_crud.get_pets(test_db)

    assert pets == []
    assert total == 0


async def test_get_pets_pagination(test_db: AsyncSession) -> None:
    """Test listing pets with pagination."""
    for i in range(15):
        await pet_crud.create_pet(test_db, "user", f"repo{i}", f"Pet{i}")

    pets, total = await pet_crud.get_pets(test_db, page=1, per_page=10)
    assert len(pets) == 10
    assert total == 15

    pets, total = await pet_crud.get_pets(test_db, page=2, per_page=10)
    assert len(pets) == 5
    assert total == 15


async def test_delete_pet(test_db: AsyncSession) -> None:
    """Test deleting a pet."""
    pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Fluffy")
    await pet_crud.delete_pet(test_db, pet)

    result = await pet_crud.get_pet_by_repo(test_db, "testuser", "testrepo")
    assert result is None


async def test_feed_pet(test_db: AsyncSession) -> None:
    """Test feeding a pet."""
    pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Fluffy")
    pet.health = 70
    await test_db.commit()

    updated_pet = await pet_crud.feed_pet(test_db, pet)

    assert updated_pet.health == 80
    assert updated_pet.mood == PetMood.HAPPY.value
    assert updated_pet.last_fed_at is not None


async def test_feed_pet_max_health(test_db: AsyncSession) -> None:
    """Test feeding a pet at max health."""
    pet = await pet_crud.create_pet(test_db, "testuser", "testrepo", "Fluffy")

    updated_pet = await pet_crud.feed_pet(test_db, pet)

    assert updated_pet.health == 100


async def test_resurrect_pet_sets_personality(test_db: AsyncSession) -> None:
    """resurrect_pet must populate all five personality fields."""
    pet = await pet_crud.create_pet(test_db, "owner", "myrepo", "Ghost")

    # Simulate a null-personality state (as if the pet predates personality generation).
    await test_db.execute(
        sa_update(Pet)
        .where(Pet.repo_owner == "owner", Pet.repo_name == "myrepo")
        .values(
            is_dead=True,
            died_at=datetime.now(UTC),
            cause_of_death="neglect",
            personality_activity=None,
            personality_sociability=None,
            personality_bravery=None,
            personality_tidiness=None,
            personality_appetite=None,
        )
    )
    await test_db.commit()
    await test_db.refresh(pet)

    resurrected = await pet_crud.resurrect_pet(test_db, pet)

    assert resurrected.personality_activity is not None
    assert resurrected.personality_sociability is not None
    assert resurrected.personality_bravery is not None
    assert resurrected.personality_tidiness is not None
    assert resurrected.personality_appetite is not None
    # Values must be in valid range
    for field in (
        resurrected.personality_activity,
        resurrected.personality_sociability,
        resurrected.personality_bravery,
        resurrected.personality_tidiness,
        resurrected.personality_appetite,
    ):
        assert 0.0 <= field <= 1.0


async def test_resurrect_pet_personality_is_deterministic(test_db: AsyncSession) -> None:
    """Personality after resurrection is stable across multiple resurrections."""
    pet = await pet_crud.create_pet(test_db, "owner2", "repo2", "Phoenix")

    # First death + resurrection
    await test_db.execute(
        sa_update(Pet)
        .where(Pet.repo_owner == "owner2", Pet.repo_name == "repo2")
        .values(is_dead=True, died_at=datetime.now(UTC), cause_of_death="neglect")
    )
    await test_db.commit()
    await test_db.refresh(pet)
    first = await pet_crud.resurrect_pet(test_db, pet)
    first_activity = first.personality_activity

    # Second death + resurrection
    await test_db.execute(
        sa_update(Pet)
        .where(Pet.repo_owner == "owner2", Pet.repo_name == "repo2")
        .values(is_dead=True, died_at=datetime.now(UTC), cause_of_death="neglect")
    )
    await test_db.commit()
    await test_db.refresh(pet)
    second = await pet_crud.resurrect_pet(test_db, pet)

    # Deterministic: same repo → same base traits
    assert second.personality_activity == first_activity
