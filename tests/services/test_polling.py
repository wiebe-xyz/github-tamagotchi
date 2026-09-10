"""Tests for repository polling functionality."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import RateLimitError, RepoHealth


async def poll_repositories() -> None:
    """Import and call poll_repositories from the current module state."""
    from github_tamagotchi.main import poll_repositories as _poll

    await _poll()


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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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
    async def test_poll_skips_pet_with_invalid_repo_identifier(self, test_db):
        """A legacy pet with a garbage repo identifier is skipped, not polled.

        Rows like this predate ``is_valid_repo_identifier`` being enforced on
        write; without this guard the poller would hit the GitHub API with
        junk on every cycle forever.
        """
        pet = Pet(
            repo_owner="owner",
            repo_name="repo)",  # trailing paren: fails _REPO_SEGMENT_RE
            name="TestPet",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        test_db.add(pet)
        await test_db.commit()

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        mock_service.get_repo_health.assert_not_called()
        await test_db.refresh(pet)
        assert pet.health == 50
        assert pet.last_checked_at is None

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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
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
        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
            mock_service = AsyncMock()
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should not raise
            await poll_repositories()

        # GitHubService should not have been called
        mock_service.get_repo_health.assert_not_called()


class TestPollFailedChecks:
    """A repo the poll can't actually read shouldn't be treated as neglected.

    See issue #185 / specs/github-app-webhooks.md: RepoHealth.failed_checks
    distinguishes "GitHub returned nothing" from "the fetch failed" (e.g. the
    shared bot account can't read a private repo) — main.py must not feed
    that into the health/mood calc as if it were genuine inactivity.
    """

    @pytest.mark.asyncio
    async def test_poll_skips_health_update_when_last_commit_check_failed(self, test_db):
        """last_commit in failed_checks should leave health/mood/experience untouched."""
        pet = Pet(
            repo_owner="owner",
            repo_name="private-repo",
            name="TestPet",
            health=50,
            experience=10,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
        )
        test_db.add(pet)
        await test_db.commit()

        unreadable_repo = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=None,
            has_stale_dependencies=False,
            failed_checks=["last_commit", "open_prs"],
        )

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = unreadable_repo
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet)
        assert pet.health == 50
        assert pet.experience == 10
        assert pet.mood == PetMood.CONTENT.value
        assert pet.last_checked_at is not None
        assert pet.last_poll_error is not None
        assert "last_commit" in pet.last_poll_error

    @pytest.mark.asyncio
    async def test_poll_clears_last_poll_error_on_recovery(self, test_db):
        """A previously-flagged pet should clear last_poll_error once the poll succeeds."""
        pet = Pet(
            repo_owner="owner",
            repo_name="repo",
            name="TestPet",
            health=50,
            experience=0,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            last_poll_error="GitHub didn't return data for this repository (last_commit)",
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

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = healthy_repo
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet)
        assert pet.last_poll_error is None

    @pytest.mark.asyncio
    async def test_poll_ignores_non_critical_failed_checks(self, test_db):
        """A failed check that isn't last_commit shouldn't block the health update."""
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

        partially_degraded_repo = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
            failed_checks=["rate_limited:contributor_count"],
        )

        with (
            patch("github_tamagotchi.main.GitHubService") as mock_service_class,
            patch("github_tamagotchi.main.async_session_factory") as mock_session_factory,
        ):
            mock_service = AsyncMock()
            mock_service.get_repo_health.return_value = partially_degraded_repo
            mock_service_class.return_value = mock_service

            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=test_db)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await poll_repositories()

        await test_db.refresh(pet)
        # +5 CI success + +10 recent commit = +15; failed_checks here doesn't
        # block the update since "last_commit" itself succeeded.
        assert pet.health == 65
        assert pet.last_poll_error is None
