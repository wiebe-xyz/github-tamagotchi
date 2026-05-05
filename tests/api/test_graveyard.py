"""Tests for graveyard API routes."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from github_tamagotchi.models.pet import Pet


@pytest.fixture
async def dead_pet(async_client: AsyncClient) -> dict[str, object]:
    """Create a dead pet via direct DB insert and return its info."""
    from tests.conftest import test_session_factory

    async with test_session_factory() as session:
        pet = Pet(
            repo_owner="testowner",
            repo_name="testrepo",
            name="Ghosty",
            health=0,
            experience=500,
            stage="child",
            mood="sick",
            is_dead=True,
            died_at=datetime.now(UTC),
            cause_of_death="neglect",
            generation=1,
            flower_count=0,
        )
        session.add(pet)
        await session.commit()
        await session.refresh(pet)
        return {
            "id": pet.id,
            "repo_owner": pet.repo_owner,
            "repo_name": pet.repo_name,
            "name": pet.name,
        }


async def test_list_graves_empty(async_client: AsyncClient) -> None:
    resp = await async_client.get("/api/v1/graveyard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["graves"] == []
    assert data["total"] == 0


async def test_list_graves_with_dead_pet(
    async_client: AsyncClient, dead_pet: dict[str, object]
) -> None:
    resp = await async_client.get("/api/v1/graveyard")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["graves"][0]["pet_name"] == "Ghosty"
    assert data["graves"][0]["cause_of_death"] == "neglect"


async def test_list_user_graves(
    async_client: AsyncClient, dead_pet: dict[str, object]
) -> None:
    resp = await async_client.get("/api/v1/graveyard/testowner")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1


async def test_list_user_graves_not_found(async_client: AsyncClient) -> None:
    resp = await async_client.get("/api/v1/graveyard/nobody")
    assert resp.status_code == 404


async def test_get_grave(
    async_client: AsyncClient, dead_pet: dict[str, object]
) -> None:
    resp = await async_client.get("/api/v1/graveyard/testowner/testrepo")
    assert resp.status_code == 200
    data = resp.json()
    assert data["grave"]["pet_name"] == "Ghosty"
    assert data["generation"] == 1
    assert data["experience"] == 500


async def test_get_grave_not_found(async_client: AsyncClient) -> None:
    resp = await async_client.get("/api/v1/graveyard/nobody/norepo")
    assert resp.status_code == 404


async def test_add_flower(
    async_client: AsyncClient, dead_pet: dict[str, object]
) -> None:
    resp = await async_client.post("/api/v1/graveyard/testowner/testrepo/flower")
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] is True
    assert data["flower_count"] == 1


async def test_add_flower_rate_limited(
    async_client: AsyncClient, dead_pet: dict[str, object]
) -> None:
    await async_client.post("/api/v1/graveyard/testowner/testrepo/flower")
    resp = await async_client.post("/api/v1/graveyard/testowner/testrepo/flower")
    assert resp.status_code == 200
    data = resp.json()
    assert data["added"] is False
    assert data["flower_count"] == 1


async def test_add_flower_not_found(async_client: AsyncClient) -> None:
    resp = await async_client.post("/api/v1/graveyard/nobody/norepo/flower")
    assert resp.status_code == 404


async def test_set_eulogy_requires_auth(
    async_client: AsyncClient, dead_pet: dict[str, object]
) -> None:
    resp = await async_client.put(
        "/api/v1/graveyard/testowner/testrepo/eulogy",
        json={"eulogy": "Rest in peace"},
    )
    assert resp.status_code == 401


async def test_set_eulogy_too_long(
    async_client: AsyncClient, dead_pet: dict[str, object]
) -> None:
    resp = await async_client.put(
        "/api/v1/graveyard/testowner/testrepo/eulogy",
        json={"eulogy": "x" * 281},
    )
    assert resp.status_code == 401  # Auth check comes first


async def test_list_graves_pagination(async_client: AsyncClient) -> None:
    from tests.conftest import test_session_factory

    async with test_session_factory() as session:
        for i in range(5):
            pet = Pet(
                repo_owner="owner",
                repo_name=f"repo{i}",
                name=f"Pet{i}",
                health=0,
                experience=0,
                stage="egg",
                mood="sick",
                is_dead=True,
                died_at=datetime.now(UTC),
                cause_of_death="neglect",
            )
            session.add(pet)
        await session.commit()

    resp = await async_client.get("/api/v1/graveyard?page=1&per_page=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["graves"]) == 2
    assert data["total"] == 5
    assert data["page"] == 1
    assert data["per_page"] == 2
