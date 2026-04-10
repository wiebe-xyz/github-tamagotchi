"""Tests for the contributor relationships API endpoint."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from github_tamagotchi.models.contributor_relationship import (
    ContributorRelationship,
    ContributorStanding,
)
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from tests.conftest import test_session_factory


async def _create_pet_with_contributors() -> int:
    """Create a pet and two contributor relationships. Returns pet id."""
    async with test_session_factory() as session:
        pet = Pet(
            repo_owner="testowner",
            repo_name="testrepo",
            name="Chippy",
            stage=PetStage.BABY.value,
            mood=PetMood.HAPPY.value,
        )
        session.add(pet)
        await session.flush()

        now = datetime.now(UTC)
        alice = ContributorRelationship(
            pet_id=pet.id,
            github_username="alice",
            standing=ContributorStanding.FAVORITE,
            score=100,
            last_activity=now - timedelta(days=1),
            good_deeds=["20 commits in last 30 days"],
            sins=[],
        )
        bob = ContributorRelationship(
            pet_id=pet.id,
            github_username="bob",
            standing=ContributorStanding.DOGHOUSE,
            score=-20,
            last_activity=now - timedelta(days=2),
            good_deeds=[],
            sins=["broke CI"],
        )
        session.add(alice)
        session.add(bob)
        await session.commit()
        return pet.id


class TestGetPetContributors:
    @pytest.mark.asyncio
    async def test_returns_contributors(self, async_client: AsyncClient) -> None:
        """Should return contributor relationships for a pet."""
        await _create_pet_with_contributors()
        response = await async_client.get("/api/v1/pets/testowner/testrepo/contributors")
        assert response.status_code == 200
        data = response.json()
        assert "contributors" in data
        assert len(data["contributors"]) >= 1

    @pytest.mark.asyncio
    async def test_returns_404_for_unknown_pet(self, async_client: AsyncClient) -> None:
        """Should return 404 when pet does not exist."""
        response = await async_client.get("/api/v1/pets/nobody/norepo/contributors")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_contributor_fields(self, async_client: AsyncClient) -> None:
        """Each contributor item should have required fields."""
        await _create_pet_with_contributors()
        response = await async_client.get("/api/v1/pets/testowner/testrepo/contributors")
        assert response.status_code == 200
        contributors = response.json()["contributors"]
        assert len(contributors) >= 1
        for c in contributors:
            assert "github_username" in c
            assert "standing" in c
            assert "score" in c
            assert "good_deeds" in c
            assert "sins" in c

    @pytest.mark.asyncio
    async def test_ordered_by_score_descending(self, async_client: AsyncClient) -> None:
        """Contributors should be ordered by score descending."""
        await _create_pet_with_contributors()
        response = await async_client.get("/api/v1/pets/testowner/testrepo/contributors")
        contributors = response.json()["contributors"]
        scores = [c["score"] for c in contributors]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_empty_when_no_contributors(self, async_client: AsyncClient) -> None:
        """Should return empty list when pet has no contributor relationships."""
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner="soloowner",
                repo_name="solorepo",
                name="Lonely",
                stage=PetStage.EGG.value,
                mood=PetMood.CONTENT.value,
            )
            session.add(pet)
            await session.commit()

        response = await async_client.get("/api/v1/pets/soloowner/solorepo/contributors")
        assert response.status_code == 200
        assert response.json()["contributors"] == []
