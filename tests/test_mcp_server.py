"""Tests for MCP server tools."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.mcp.server import (
    _calculate_stage_progress,
    check_pet_status,
    feed_pet,
    get_pet_history,
    list_pets,
    register_pet,
    update_pet_from_repo,
)
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import RepoHealth

# Access the underlying functions from FastMCP tool wrappers
_register_pet = register_pet.fn
_check_pet_status = check_pet_status.fn
_feed_pet = feed_pet.fn
_list_pets = list_pets.fn
_get_pet_history = get_pet_history.fn
_update_pet_from_repo = update_pet_from_repo.fn


@pytest.fixture
def mock_repo_health() -> RepoHealth:
    """Create a mock repository health object."""
    return RepoHealth(
        last_commit_at=datetime.now(UTC),
        open_prs_count=2,
        oldest_pr_age_hours=24,
        open_issues_count=5,
        oldest_issue_age_days=3,
        last_ci_success=True,
        has_stale_dependencies=False,
    )


class TestRegisterPet:
    """Tests for the register_pet MCP tool."""

    async def test_register_pet_creates_new_pet(self, test_db: AsyncSession) -> None:
        """Should create a new pet for a repository."""
        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _register_pet("owner", "repo", "TestPet")

        assert "error" not in result
        assert result["pet"]["name"] == "TestPet"
        assert result["pet"]["stage"] == PetStage.EGG.value
        assert result["pet"]["health"] == 100
        assert "hatched" in result["message"]

    async def test_register_pet_duplicate_fails(self, test_db: AsyncSession) -> None:
        """Should fail when creating a duplicate pet."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="ExistingPet",
            stage=PetStage.BABY.value,
            mood=PetMood.HAPPY.value,
            health=100,
            experience=100,
        )
        test_db.add(pet)
        await test_db.commit()

        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _register_pet("owner", "repo", "AnotherPet")

        assert "error" in result
        assert "already exists" in result["error"]


class TestCheckPetStatus:
    """Tests for the check_pet_status MCP tool."""

    async def test_check_pet_status_returns_pet_info(
        self, test_db: AsyncSession, mock_repo_health: RepoHealth
    ) -> None:
        """Should return pet information when pet exists."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            stage=PetStage.BABY.value,
            mood=PetMood.HAPPY.value,
            health=90,
            experience=150,
        )
        test_db.add(pet)
        await test_db.commit()

        with (
            patch(
                "github_tamagotchi.mcp.server.async_session_factory"
            ) as mock_factory,
            patch(
                "github_tamagotchi.mcp.server.GitHubService"
            ) as mock_github,
        ):
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_github.return_value.get_repo_health = AsyncMock(
                return_value=mock_repo_health
            )

            result = await _check_pet_status("owner", "repo")

        assert "error" not in result
        assert result["pet"]["name"] == "TestPet"
        assert result["pet"]["stage"] == PetStage.BABY.value
        assert result["health_metrics"]["ci_passing"] is True

    async def test_check_pet_status_no_pet(self, test_db: AsyncSession) -> None:
        """Should return error when no pet exists."""
        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _check_pet_status("owner", "nonexistent")

        assert "error" in result
        assert "No pet found" in result["error"]


class TestFeedPet:
    """Tests for the feed_pet MCP tool."""

    async def test_feed_pet_increases_health(self, test_db: AsyncSession) -> None:
        """Should increase pet health when fed."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            stage=PetStage.BABY.value,
            mood=PetMood.HUNGRY.value,
            health=80,
            experience=50,
        )
        test_db.add(pet)
        await test_db.commit()

        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _feed_pet("owner", "repo")

        assert "error" not in result
        assert result["pet"]["health"] == 90
        assert result["pet"]["mood"] == PetMood.HAPPY.value
        assert result["health_change"] == 10

    async def test_feed_pet_caps_at_100(self, test_db: AsyncSession) -> None:
        """Should not exceed 100 health when fed."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            stage=PetStage.BABY.value,
            mood=PetMood.CONTENT.value,
            health=95,
            experience=50,
        )
        test_db.add(pet)
        await test_db.commit()

        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _feed_pet("owner", "repo")

        assert result["pet"]["health"] == 100
        assert result["health_change"] == 5

    async def test_feed_pet_no_pet(self, test_db: AsyncSession) -> None:
        """Should return error when no pet exists."""
        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _feed_pet("owner", "nonexistent")

        assert "error" in result


class TestListPets:
    """Tests for the list_pets MCP tool."""

    async def test_list_pets_empty(self, test_db: AsyncSession) -> None:
        """Should return empty list when no pets exist."""
        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _list_pets()

        assert result["pets"] == []
        assert result["count"] == 0

    async def test_list_pets_returns_all(self, test_db: AsyncSession) -> None:
        """Should return all registered pets."""
        pet1 = Pet(
            repo_owner="owner1",
            repo_name="repo1",
            name="Pet1",
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=100,
            experience=0,
        )
        pet2 = Pet(
            repo_owner="owner2",
            repo_name="repo2",
            name="Pet2",
            stage=PetStage.ADULT.value,
            mood=PetMood.HAPPY.value,
            health=85,
            experience=5000,
        )
        test_db.add_all([pet1, pet2])
        await test_db.commit()

        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _list_pets()

        assert result["count"] == 2
        assert len(result["pets"]) == 2
        names = [p["name"] for p in result["pets"]]
        assert "Pet1" in names
        assert "Pet2" in names


class TestGetPetHistory:
    """Tests for the get_pet_history MCP tool."""

    async def test_get_pet_history_shows_evolution(
        self, test_db: AsyncSession
    ) -> None:
        """Should show pet evolution history."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            stage=PetStage.TEEN.value,
            mood=PetMood.HAPPY.value,
            health=100,
            experience=2000,
        )
        test_db.add(pet)
        await test_db.commit()

        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _get_pet_history("owner", "repo")

        assert "error" not in result
        assert result["pet"]["current_stage"] == PetStage.TEEN.value
        assert PetStage.EGG.value in result["evolution"]["stages_completed"]
        assert PetStage.BABY.value in result["evolution"]["stages_completed"]
        assert PetStage.ADULT.value in result["evolution"]["stages_remaining"]

    async def test_get_pet_history_no_pet(self, test_db: AsyncSession) -> None:
        """Should return error when no pet exists."""
        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _get_pet_history("owner", "nonexistent")

        assert "error" in result


class TestUpdatePetFromRepo:
    """Tests for the update_pet_from_repo MCP tool."""

    async def test_update_pet_from_repo(
        self, test_db: AsyncSession, mock_repo_health: RepoHealth
    ) -> None:
        """Should update pet based on repo health."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            stage=PetStage.BABY.value,
            mood=PetMood.CONTENT.value,
            health=50,
            experience=100,
        )
        test_db.add(pet)
        await test_db.commit()

        with (
            patch(
                "github_tamagotchi.mcp.server.async_session_factory"
            ) as mock_factory,
            patch(
                "github_tamagotchi.mcp.server.GitHubService"
            ) as mock_github,
        ):
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_github.return_value.get_repo_health = AsyncMock(
                return_value=mock_repo_health
            )

            result = await _update_pet_from_repo("owner", "repo")

        assert "error" not in result
        assert "changes" in result
        assert result["pet"]["mood"] == PetMood.DANCING.value

    async def test_update_pet_from_repo_no_pet(self, test_db: AsyncSession) -> None:
        """Should return error when no pet exists."""
        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _update_pet_from_repo("owner", "nonexistent")

        assert "error" in result


class TestFeedPetEvolution:
    """Tests for pet evolution during feeding."""

    async def test_feed_pet_triggers_evolution(self, test_db: AsyncSession) -> None:
        """Should trigger evolution when experience crosses threshold."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=80,
            experience=96,  # +5 from feeding will reach 101, crossing BABY threshold of 100
        )
        test_db.add(pet)
        await test_db.commit()

        with patch(
            "github_tamagotchi.mcp.server.async_session_factory"
        ) as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _feed_pet("owner", "repo")

        assert "error" not in result
        assert result["pet"]["stage"] == PetStage.BABY.value
        assert "evolution" in result
        assert "evolved" in result["evolution"]


class TestCalculateStageProgress:
    """Tests for the _calculate_stage_progress helper function."""

    def test_progress_mid_stage(self) -> None:
        """Should calculate correct progress percentage."""
        result = _calculate_stage_progress(300, PetStage.BABY.value)
        assert result["at_max_stage"] is False
        assert result["next_stage"] == PetStage.CHILD.value
        assert result["current_exp"] == 300
        assert result["exp_needed"] == 500
        assert result["percentage"] == 50  # (300 - 100) / (500 - 100) = 50%

    def test_progress_at_max_stage(self) -> None:
        """Should indicate max stage reached."""
        result = _calculate_stage_progress(20000, PetStage.ELDER.value)
        assert result["at_max_stage"] is True
        assert result["percentage"] == 100

    def test_progress_at_start(self) -> None:
        """Should show 0% progress at the start of a stage."""
        result = _calculate_stage_progress(100, PetStage.BABY.value)
        assert result["at_max_stage"] is False
        assert result["percentage"] == 0
