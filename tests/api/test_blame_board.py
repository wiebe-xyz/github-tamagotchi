"""Tests for the blame/heroes board API endpoint."""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import BlameBoardData, BlameEntry, HeroEntry


async def _create_pet(
    session_factory,
    repo_owner: str = "testowner",
    repo_name: str = "testrepo",
    health: int = 80,
    mood: str = PetMood.HAPPY.value,
    blame_board_enabled: bool = True,
    is_dead: bool = False,
) -> None:
    async with session_factory() as session:
        pet = Pet(
            repo_owner=repo_owner,
            repo_name=repo_name,
            name="Gotchi",
            stage=PetStage.BABY.value,
            mood=mood,
            health=health,
            experience=150,
            blame_board_enabled=blame_board_enabled,
            is_dead=is_dead,
        )
        session.add(pet)
        await session.commit()


class TestBlameBoardEndpoint:
    """Tests for GET /api/v1/pets/{owner}/{repo}/blame-board."""

    async def test_returns_404_for_missing_pet(self, async_client: AsyncClient) -> None:
        """Should return 404 when pet does not exist."""
        response = await async_client.get("/api/v1/pets/noowner/norepo/blame-board")
        assert response.status_code == 404

    async def test_returns_empty_when_disabled(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Should return empty lists when blame_board_enabled is False."""
        from tests.conftest import test_session_factory

        await _create_pet(test_session_factory, blame_board_enabled=False)

        response = await async_client.get("/api/v1/pets/testowner/testrepo/blame-board")
        assert response.status_code == 200
        data = response.json()
        assert data["blame_board_enabled"] is False
        assert data["blame_entries"] == []
        assert data["hero_entries"] == []

    async def test_returns_empty_for_dead_pet(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Should return empty lists for dead pets."""
        from tests.conftest import test_session_factory

        await _create_pet(test_session_factory, is_dead=True)

        response = await async_client.get("/api/v1/pets/testowner/testrepo/blame-board")
        assert response.status_code == 200
        data = response.json()
        assert data["blame_entries"] == []
        assert data["hero_entries"] == []

    async def test_returns_heroes_for_healthy_pet(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Should return hero entries for a healthy pet."""
        from tests.conftest import test_session_factory

        await _create_pet(test_session_factory, health=80, mood=PetMood.HAPPY.value)

        board = BlameBoardData(
            is_healthy=True,
            blame_entries=[],
            hero_entries=[
                HeroEntry(good_deed="Merged 5 PRs", hero="alice", when="This week"),
            ],
        )
        with patch(
            "github_tamagotchi.api.routes.GitHubService.get_blame_board_data",
            new_callable=AsyncMock,
            return_value=board,
        ):
            response = await async_client.get("/api/v1/pets/testowner/testrepo/blame-board")

        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is True
        assert data["blame_board_enabled"] is True
        assert len(data["hero_entries"]) == 1
        assert data["hero_entries"][0]["hero"] == "alice"
        assert data["hero_entries"][0]["good_deed"] == "Merged 5 PRs"
        assert data["blame_entries"] == []

    async def test_returns_blame_for_unhealthy_pet(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Should return blame entries for an unhealthy pet."""
        from tests.conftest import test_session_factory

        await _create_pet(test_session_factory, health=30, mood=PetMood.WORRIED.value)

        board = BlameBoardData(
            is_healthy=False,
            blame_entries=[
                BlameEntry(issue="CI broken", culprit="charlie", how_long="2 days"),
                BlameEntry(issue="PR #42 needs review", culprit="alice", how_long="4 days"),
            ],
            hero_entries=[],
        )
        with patch(
            "github_tamagotchi.api.routes.GitHubService.get_blame_board_data",
            new_callable=AsyncMock,
            return_value=board,
        ):
            response = await async_client.get("/api/v1/pets/testowner/testrepo/blame-board")

        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["blame_board_enabled"] is True
        assert len(data["blame_entries"]) == 2
        assert data["blame_entries"][0]["culprit"] == "charlie"
        assert data["blame_entries"][0]["issue"] == "CI broken"
        assert data["blame_entries"][0]["how_long"] == "2 days"
        assert data["hero_entries"] == []

    async def test_response_schema_keys_present(
        self, async_client: AsyncClient, test_db: object
    ) -> None:
        """Response should always include required schema keys."""
        from tests.conftest import test_session_factory

        await _create_pet(test_session_factory, blame_board_enabled=False)

        response = await async_client.get("/api/v1/pets/testowner/testrepo/blame-board")
        data = response.json()
        assert "is_healthy" in data
        assert "blame_board_enabled" in data
        assert "blame_entries" in data
        assert "hero_entries" in data
