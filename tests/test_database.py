"""Tests for database module."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood, PetStage


async def test_session_provides_working_connection(test_db: AsyncSession) -> None:
    """Test that the session can execute queries."""
    result = await test_db.execute(text("SELECT 1"))
    assert result.scalar() == 1


async def test_session_can_create_pet(test_db: AsyncSession) -> None:
    """Test that we can create a pet using the session."""
    pet = Pet(
        repo_owner="test-owner",
        repo_name="test-repo",
        name="TestPet",
        stage=PetStage.EGG.value,
        mood=PetMood.CONTENT.value,
        health=100,
        experience=0,
    )
    test_db.add(pet)
    await test_db.commit()
    await test_db.refresh(pet)

    assert pet.id is not None
    assert pet.repo_owner == "test-owner"
    assert pet.repo_name == "test-repo"
    assert pet.name == "TestPet"


async def test_session_can_query_pet(test_db: AsyncSession) -> None:
    """Test that we can query pets from the database."""
    pet = Pet(
        repo_owner="query-owner",
        repo_name="query-repo",
        name="QueryPet",
    )
    test_db.add(pet)
    await test_db.commit()

    result = await test_db.execute(select(Pet).where(Pet.repo_owner == "query-owner"))
    found_pet = result.scalar_one_or_none()
    assert found_pet is not None
    assert found_pet.name == "QueryPet"


async def test_pet_default_values(test_db: AsyncSession) -> None:
    """Test that pet has correct default values."""
    pet = Pet(
        repo_owner="default-owner",
        repo_name="default-repo",
        name="DefaultPet",
    )
    test_db.add(pet)
    await test_db.commit()
    await test_db.refresh(pet)

    assert pet.stage == PetStage.EGG.value
    assert pet.mood == PetMood.CONTENT.value
    assert pet.health == 100
    assert pet.experience == 0
    assert pet.created_at is not None
    assert pet.updated_at is not None
