"""Tests for the achievements service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.achievement import PetAchievement
from github_tamagotchi.models.pet import PetStage
from github_tamagotchi.services.achievements import (
    ACHIEVEMENT_ORDER,
    ACHIEVEMENTS,
    check_and_unlock_achievements,
    get_pet_achievements,
)


async def test_first_commit_achievement(test_db: AsyncSession) -> None:
    """first_commit unlocks when pet has experience > 0."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo", "Buddy")
    pet.experience = 10
    pet.commit_streak = 1
    await test_db.flush()

    newly = await check_and_unlock_achievements(pet, test_db)

    assert "first_commit" in newly


async def test_week_warrior_achievement(test_db: AsyncSession) -> None:
    """week_warrior unlocks at commit_streak >= 7."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo2", "Max")
    pet.commit_streak = 7
    pet.longest_streak = 7
    pet.experience = 100
    await test_db.flush()

    newly = await check_and_unlock_achievements(pet, test_db)

    assert "week_warrior" in newly
    assert "first_commit" in newly


async def test_month_legend_achievement(test_db: AsyncSession) -> None:
    """month_legend unlocks at longest_streak >= 30."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo3", "Titan")
    pet.longest_streak = 30
    pet.commit_streak = 30
    pet.experience = 500
    await test_db.flush()

    newly = await check_and_unlock_achievements(pet, test_db)

    assert "month_legend" in newly


async def test_stage_achievements(test_db: AsyncSession) -> None:
    """Stage-based achievements unlock at correct stages."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo4", "Elder")
    pet.stage = PetStage.ELDER.value
    pet.experience = 10000
    await test_db.flush()

    newly = await check_and_unlock_achievements(pet, test_db)

    assert "hatchling" in newly
    assert "all_grown_up" in newly
    assert "elder_god" in newly


async def test_no_achievements_for_egg_no_activity(test_db: AsyncSession) -> None:
    """A fresh egg with no activity should not unlock first_commit."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo5", "Newbie")
    # Defaults: egg stage, health=100, experience=0, streak=0

    newly = await check_and_unlock_achievements(pet, test_db)

    assert "first_commit" not in newly
    assert "week_warrior" not in newly


async def test_centurion_achievement(test_db: AsyncSession) -> None:
    """centurion unlocks when health == 100."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo6", "Healthy")
    pet.health = 100
    await test_db.flush()

    newly = await check_and_unlock_achievements(pet, test_db)

    assert "centurion" in newly


async def test_phoenix_achievement(test_db: AsyncSession) -> None:
    """phoenix unlocks when generation >= 2."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo7", "Reborn")
    pet.generation = 2
    pet.experience = 1
    pet.commit_streak = 1
    await test_db.flush()

    newly = await check_and_unlock_achievements(pet, test_db)

    assert "phoenix" in newly


async def test_duplicate_unlock_is_idempotent(test_db: AsyncSession) -> None:
    """Calling check_and_unlock twice does not create duplicate rows."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo8", "Duper")
    pet.experience = 10
    pet.commit_streak = 1
    await test_db.flush()

    first = await check_and_unlock_achievements(pet, test_db)
    second = await check_and_unlock_achievements(pet, test_db)

    # second call should return empty (already unlocked)
    for aid in first:
        assert aid not in second

    # DB should have exactly one row per achievement
    result = await test_db.execute(
        select(PetAchievement).where(PetAchievement.pet_id == pet.id)
    )
    rows = result.scalars().all()
    achievement_ids = [r.achievement_id for r in rows]
    assert len(achievement_ids) == len(set(achievement_ids))


async def test_get_pet_achievements_returns_all_slots(test_db: AsyncSession) -> None:
    """get_pet_achievements returns all 10 achievement slots."""
    pet = await pet_crud.create_pet(test_db, "owner", "repo9", "Checker")
    pet.experience = 10
    pet.commit_streak = 1
    await test_db.flush()

    await check_and_unlock_achievements(pet, test_db)
    achievement_map = await get_pet_achievements(pet.id, test_db)

    assert set(achievement_map.keys()) == set(ACHIEVEMENT_ORDER)
    assert len(achievement_map) == len(ACHIEVEMENTS)


async def test_achievements_api_endpoint(async_client: object) -> None:
    """GET /api/v1/pets/{owner}/{repo}/achievements returns correct shape."""
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    # Create a pet first
    resp = await client.post(
        "/api/v1/pets",
        json={"repo_owner": "owner", "repo_name": "repo10", "name": "API Pet"},
    )
    assert resp.status_code == 201

    # Fetch achievements
    resp = await client.get("/api/v1/pets/owner/repo10/achievements")
    assert resp.status_code == 200
    data = resp.json()
    assert "achievements" in data
    assert len(data["achievements"]) == len(ACHIEVEMENTS)

    for item in data["achievements"]:
        assert "id" in item
        assert "name" in item
        assert "icon" in item
        assert "description" in item
        assert "unlocked" in item
        assert "unlocked_at" in item


async def test_achievements_api_404_for_unknown_pet(async_client: object) -> None:
    """GET achievements for unknown pet returns 404."""
    from httpx import AsyncClient

    client: AsyncClient = async_client  # type: ignore[assignment]

    resp = await client.get("/api/v1/pets/nobody/norepo/achievements")
    assert resp.status_code == 404
