"""Tests for repository polling functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from github_tamagotchi.main import poll_repositories
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import RateLimitError, RepoHealth


class TestPollRepositories:
    """Tests for the poll_repositories function."""

    @pytest.mark.asyncio
    async def test_poll_updates_pet_health_on_healthy_repo(self, test_db):
        """Pet health should increase when repo is healthy."""
        # Create a pet
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        test_db.add(pet)
        await test_db.commit()

        # Mock healthy repo health
        healthy_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = healthy_repo
            mock_service_class.return_value = mock_service

            # Mock session context manager
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        # Verify pet was updated
        await test_db.refresh(pet)
        # +5 for CI success + +10 for recent commit = +15
        assert pet.health == 65
        # +10 for CI + +20 for recent commit = 30
        assert pet.experience == 30
        assert pet.mood == PetMood.DANCING.value
        assert pet.last_checked_at is not None

    @pytest.mark.asyncio
    async def test_poll_decreases_health_on_unhealthy_repo(self, test_db):
        """Pet health should decrease when repo is unhealthy."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            health=50,
            experience=0,
            stage=PetStage.BABY.value,
            mood=PetMood.HAPPY.value,
        )
        test_db.add(pet)
        await test_db.commit()

        unhealthy_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(days=10),
            open_prs_count=5,
            oldest_pr_age_hours=100,
            open_issues_count=20,
            oldest_issue_age_days=30,
            last_ci_success=False,
            has_stale_dependencies=True,
        )

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = unhealthy_repo
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet)
        # -10 stale deps + -5 old PR + -5 old issues = -20
        assert pet.health == 30
        assert pet.mood == PetMood.SICK.value

    @pytest.mark.asyncio
    async def test_poll_triggers_evolution(self, test_db):
        """Pet should evolve when experience threshold is met."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            health=80,
            experience=90,  # Close to baby threshold (100)
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        test_db.add(pet)
        await test_db.commit()

        healthy_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = healthy_repo
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet)
        # 90 + 30 = 120 >= 100 threshold for baby
        assert pet.experience == 120
        assert pet.stage == PetStage.BABY.value

    @pytest.mark.asyncio
    async def test_poll_handles_rate_limit_gracefully(self, test_db):
        """Polling should stop when rate limit is hit."""
        pet1 = Pet(
            repo_owner="owner1",
            repo_name="repo1",
            name="Pet1",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        pet2 = Pet(
            repo_owner="owner2",
            repo_name="repo2",
            name="Pet2",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        test_db.add_all([pet1, pet2])
        await test_db.commit()

        reset_time = datetime.now(UTC) + timedelta(hours=1)

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            # First call hits rate limit
            mock_service.get_repo_health.side_effect = RateLimitError(
                "Rate limit exceeded", reset_time=reset_time
            )
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should not raise, but should stop polling
            await poll_repositories()

        await test_db.refresh(pet1)
        await test_db.refresh(pet2)
        # Both pets should be unchanged since we stopped at rate limit
        assert pet1.health == 50
        assert pet2.health == 50

    @pytest.mark.asyncio
    async def test_poll_continues_on_individual_errors(self, test_db):
        """Polling should continue with other pets when one fails."""
        pet1 = Pet(
            repo_owner="owner1",
            repo_name="repo1",
            name="Pet1",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        pet2 = Pet(
            repo_owner="owner2",
            repo_name="repo2",
            name="Pet2",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        test_db.add_all([pet1, pet2])
        await test_db.commit()

        healthy_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            # First pet fails, second succeeds
            mock_service.get_repo_health.side_effect = [
                Exception("Network error"),
                healthy_repo,
            ]
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet1)
        await test_db.refresh(pet2)
        # Pet1 unchanged due to error, Pet2 updated
        assert pet1.health == 50
        assert pet2.health == 65  # +15 health delta

    @pytest.mark.asyncio
    async def test_poll_clamps_health_to_bounds(self, test_db):
        """Health should be clamped between 0 and 100."""
        pet_low = Pet(
            repo_owner="owner1",
            repo_name="repo1",
            name="LowPet",
            health=5,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        pet_high = Pet(
            repo_owner="owner2",
            repo_name="repo2",
            name="HighPet",
            health=95,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        test_db.add_all([pet_low, pet_high])
        await test_db.commit()

        # Very unhealthy repo (-20 health delta)
        unhealthy_repo = RepoHealth(
            last_commit_at=None,
            open_prs_count=1,
            oldest_pr_age_hours=100,
            open_issues_count=5,
            oldest_issue_age_days=30,
            last_ci_success=False,
            has_stale_dependencies=True,
        )

        # Very healthy repo (+15 health delta)
        healthy_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            mock_service.get_repo_health.side_effect = [unhealthy_repo, healthy_repo]
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet_low)
        await test_db.refresh(pet_high)
        # 5 - 20 = -15, clamped to 0
        assert pet_low.health == 0
        # 95 + 15 = 110, clamped to 100
        assert pet_high.health == 100

    @pytest.mark.asyncio
    async def test_poll_updates_last_fed_at_on_recent_commit(self, test_db):
        """Last fed should be updated when there's a recent commit."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            last_fed_at=None,
        )
        test_db.add(pet)
        await test_db.commit()

        healthy_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = healthy_repo
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet)
        assert pet.last_fed_at is not None

    @pytest.mark.asyncio
    async def test_poll_does_not_update_last_fed_on_old_commit(self, test_db):
        """Last fed should not be updated when commit is old."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            last_fed_at=None,
        )
        test_db.add(pet)
        await test_db.commit()

        old_commit_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=30),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )

        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = old_commit_repo
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet)
        assert pet.last_fed_at is None

    @pytest.mark.asyncio
    async def test_poll_with_no_pets(self, test_db):
        """Polling should complete without errors when no pets exist."""
        with patch(
            "github_tamagotchi.main.GitHubService"
        ) as mock_service_class, patch(
            "github_tamagotchi.main.async_session_factory"
        ) as mock_session_factory:
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should not raise
            await poll_repositories()

        # GitHubService should not have been called
        mock_service.get_repo_health.assert_not_called()
