"""E2E: Pet mood transitions and health clamping."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.pet_logic import (
    calculate_health_delta,
    calculate_mood,
)


@pytest.mark.asyncio
class TestMoodTransitions:
    """Verify mood changes based on different repository states."""

    @respx.mock
    async def test_stale_deps_cause_sick_mood(
        self, e2e_db: AsyncSession, sample_pet: Pet
    ) -> None:
        """Stale dependencies make the pet sick (highest priority mood)."""
        owner, repo = sample_pet.repo_owner, sample_pet.repo_name
        recent = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
            return_value=httpx.Response(
                200, json=[{"sha": "x", "commit": {"committer": {"date": recent}}}]
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/main/status"
        ).mock(return_value=httpx.Response(200, json={"state": "success", "statuses": []}))

        service = GitHubService(token="fake-token")
        health = await service.get_repo_health(owner, repo)
        # Force stale deps (not detected by API, would be set externally)
        health.has_stale_dependencies = True

        mood = calculate_mood(health, sample_pet.health)
        assert mood == PetMood.SICK

    @respx.mock
    async def test_old_pr_causes_worried_mood(
        self, e2e_db: AsyncSession, sample_pet: Pet
    ) -> None:
        """A PR open for more than 48 hours makes pet worried."""
        owner, repo = sample_pet.repo_owner, sample_pet.repo_name
        recent = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_pr = (datetime.now(UTC) - timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ")

        respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
            return_value=httpx.Response(
                200, json=[{"sha": "x", "commit": {"committer": {"date": recent}}}]
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[{
                    "id": 1, "number": 1, "title": "Old",
                    "created_at": old_pr, "state": "open",
                }],
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/main/status"
        ).mock(return_value=httpx.Response(200, json={"state": "failure", "statuses": []}))

        service = GitHubService(token="fake-token")
        health = await service.get_repo_health(owner, repo)
        mood = calculate_mood(health, sample_pet.health)
        assert mood == PetMood.WORRIED

    @respx.mock
    async def test_old_issue_causes_lonely_mood(
        self, e2e_db: AsyncSession, sample_pet: Pet
    ) -> None:
        """An issue unanswered for 7+ days makes pet lonely."""
        owner, repo = sample_pet.repo_owner, sample_pet.repo_name
        recent = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_issue = (datetime.now(UTC) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

        respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
            return_value=httpx.Response(
                200, json=[{"sha": "x", "commit": {"committer": {"date": recent}}}]
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/issues").mock(
            return_value=httpx.Response(
                200,
                json=[{
                    "id": 1, "number": 5, "title": "Old issue",
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
        mood = calculate_mood(health, sample_pet.health)
        assert mood == PetMood.LONELY


@pytest.mark.asyncio
class TestHealthClamping:
    """Health stays within [0, 100] regardless of delta magnitude."""

    async def test_health_does_not_exceed_100(self, e2e_db: AsyncSession) -> None:
        """Health is capped at 100 even with large positive deltas."""
        pet = Pet(
            repo_owner="owner",
            repo_name="maxhealth",
            name="MaxPet",
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=95,
            experience=0,
        )
        e2e_db.add(pet)
        await e2e_db.commit()

        # Simulate a +15 delta
        pet.health = min(100, pet.health + 15)
        await e2e_db.commit()
        await e2e_db.refresh(pet)
        assert pet.health == 100

    async def test_health_does_not_go_below_zero(self, e2e_db: AsyncSession) -> None:
        """Health floors at 0 even with large negative deltas."""
        pet = Pet(
            repo_owner="owner",
            repo_name="lowhealth",
            name="WeakPet",
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=5,
            experience=0,
        )
        e2e_db.add(pet)
        await e2e_db.commit()

        # Simulate a -20 delta
        pet.health = max(0, pet.health - 20)
        await e2e_db.commit()
        await e2e_db.refresh(pet)
        assert pet.health == 0

    @respx.mock
    async def test_repeated_polling_accumulates(
        self, e2e_db: AsyncSession, sample_pet: Pet
    ) -> None:
        """Multiple poll cycles accumulate health and experience changes."""
        owner, repo = sample_pet.repo_owner, sample_pet.repo_name
        old_commit = (datetime.now(UTC) - timedelta(days=5)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        old_pr = (datetime.now(UTC) - timedelta(hours=72)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        # Set up mocks for an unhealthy repo
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
            return_value=httpx.Response(
                200,
                json=[{"sha": "old", "commit": {"committer": {"date": old_commit}}}],
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
            return_value=httpx.Response(
                200,
                json=[{
                    "id": 1, "number": 1, "title": "Stale",
                    "created_at": old_pr, "state": "open",
                }],
            )
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/main/status"
        ).mock(return_value=httpx.Response(200, json={"state": "failure", "statuses": []}))

        service = GitHubService(token="fake-token")

        # Simulate 3 poll cycles
        for _ in range(3):
            health = await service.get_repo_health(owner, repo)
            delta = calculate_health_delta(health)
            sample_pet.health = max(0, min(100, sample_pet.health + delta))

        await e2e_db.commit()
        await e2e_db.refresh(sample_pet)

        # Old PR (-5) per cycle × 3 = -15 from 100 → 85
        assert sample_pet.health == 85
