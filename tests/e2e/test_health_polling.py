"""E2E: GitHub health polling — fetch repo health, update pet state."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.pet_logic import (
    calculate_experience,
    calculate_health_delta,
    calculate_mood,
    get_next_stage,
)

from .conftest import mock_github_repo


@pytest.mark.asyncio
class TestHealthPolling:
    """Full flow: mock GitHub API → fetch health → update pet."""

    @respx.mock
    async def test_healthy_repo_updates_pet(
        self, e2e_db: AsyncSession, sample_pet: Pet
    ) -> None:
        """A healthy repo increases pet health and experience."""
        owner, repo = sample_pet.repo_owner, sample_pet.repo_name
        mock_github_repo(owner, repo, commit_age_hours=2)

        service = GitHubService(token="fake-token")
        health = await service.get_repo_health(owner, repo)

        # Apply pet logic
        delta = calculate_health_delta(health)
        exp = calculate_experience(health)
        mood = calculate_mood(health, sample_pet.health + delta)

        # Update pet in DB
        sample_pet.health = max(0, min(100, sample_pet.health + delta))
        sample_pet.experience += exp
        sample_pet.mood = mood.value
        sample_pet.stage = get_next_stage(
            PetStage(sample_pet.stage), sample_pet.experience
        ).value
        sample_pet.last_checked_at = datetime.now(UTC)
        await e2e_db.commit()
        await e2e_db.refresh(sample_pet)

        # Healthy repo: CI success (+5) and recent commit (+10) = +15 health
        assert sample_pet.health == 100  # capped at 100
        assert delta == 15
        # CI success (+10) and recent commit (+20) = +30 exp
        assert sample_pet.experience == 30
        assert exp == 30
        # CI success → dancing mood
        assert sample_pet.mood == PetMood.DANCING.value
        assert sample_pet.last_checked_at is not None

    @respx.mock
    async def test_unhealthy_repo_decreases_pet_health(
        self, e2e_db: AsyncSession, sample_pet: Pet
    ) -> None:
        """A neglected repo decreases pet health and triggers negative mood."""
        owner, repo = sample_pet.repo_owner, sample_pet.repo_name
        old_commit = (datetime.now(UTC) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        old_pr = (datetime.now(UTC) - timedelta(hours=100)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        old_issue = (datetime.now(UTC) - timedelta(days=14)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
            return_value=httpx.Response(
                200, json=[{"sha": "old", "commit": {"committer": {"date": old_commit}}}]
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[{
                    "id": 1, "number": 1, "title": "Stale PR",
                    "created_at": old_pr, "state": "open",
                }],
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/issues").mock(
            return_value=httpx.Response(
                200,
                json=[{
                    "id": 1, "number": 10, "title": "Old issue",
                    "created_at": old_issue, "state": "open",
                }],
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/main/status"
        ).mock(return_value=httpx.Response(200, json={"state": "failure", "statuses": []}))

        service = GitHubService(token="fake-token")
        health = await service.get_repo_health(owner, repo)

        delta = calculate_health_delta(health)
        exp = calculate_experience(health)
        mood = calculate_mood(health, sample_pet.health + delta)

        sample_pet.health = max(0, min(100, sample_pet.health + delta))
        sample_pet.experience += exp
        sample_pet.mood = mood.value
        await e2e_db.commit()
        await e2e_db.refresh(sample_pet)

        # Old PR (-5), old issue (-5) = -10
        assert delta == -10
        assert sample_pet.health == 90
        assert exp == 0  # No positive activity
        # No recent commits → hungry (>3 days)
        assert sample_pet.mood == PetMood.HUNGRY.value

    @respx.mock
    async def test_github_api_failure_is_handled(
        self, e2e_db: AsyncSession, sample_pet: Pet
    ) -> None:
        """GitHub API errors don't crash the polling flow."""
        owner, repo = sample_pet.repo_owner, sample_pet.repo_name

        respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
            return_value=httpx.Response(500)
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
            return_value=httpx.Response(500)
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/issues").mock(
            return_value=httpx.Response(500)
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
            return_value=httpx.Response(500)
        )

        service = GitHubService(token="fake-token")
        health = await service.get_repo_health(owner, repo)

        # Service handles errors gracefully — returns defaults
        assert health.last_commit_at is None
        assert health.open_prs_count == 0
        assert health.open_issues_count == 0
        assert health.last_ci_success is None
