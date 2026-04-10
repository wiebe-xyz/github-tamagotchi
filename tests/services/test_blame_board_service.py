"""Tests for GitHubService blame board methods."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from github_tamagotchi.services.github import GitHubService


def _make_commit(login: str, days_ago: int = 0) -> dict[str, Any]:
    dt = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    return {
        "sha": f"sha_{login}_{days_ago}",
        "author": {"login": login},
        "commit": {"committer": {"date": dt}},
    }


def _make_pr(
    number: int,
    title: str,
    days_old: int = 3,
    reviewers: list[str] | None = None,
    author: str = "prauthor",
) -> dict[str, Any]:
    created = (datetime.now(UTC) - timedelta(days=days_old)).isoformat()
    return {
        "number": number,
        "title": title,
        "created_at": created,
        "user": {"login": author},
        "requested_reviewers": [{"login": r} for r in (reviewers or [])],
    }


class TestFormatDuration:
    """Tests for _format_duration helper."""

    def test_just_now(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(minutes=30)
        assert service._format_duration(dt) == "just now"

    def test_hours(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(hours=5)
        result = service._format_duration(dt)
        assert "hours" in result

    def test_days(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(days=3)
        result = service._format_duration(dt)
        assert "days" in result or "day" in result

    def test_one_day(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(hours=25)
        result = service._format_duration(dt)
        assert result == "1 day"


class TestFormatWhen:
    """Tests for _format_when helper."""

    def test_today(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(hours=2)
        assert service._format_when(dt) == "Today"

    def test_yesterday(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(hours=30)
        assert service._format_when(dt) == "Yesterday"

    def test_this_week(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(days=5)
        assert service._format_when(dt) == "This week"

    def test_days_ago(self) -> None:
        service = GitHubService(token=None)
        dt = datetime.now(UTC) - timedelta(days=10)
        result = service._format_when(dt)
        assert "ago" in result


class TestGetBlameBoardData:
    """Tests for get_blame_board_data orchestration."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_healthy_pet_returns_is_healthy_true(self) -> None:
        """A healthy pet (health >= 50, happy mood) should yield is_healthy=True."""
        # Mock all GitHub API calls to return empty/success
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[_make_commit("alice")])
        )
        respx.get(
            "https://api.github.com/repos/owner/repo/commits/sha_alice_0/check-runs"
        ).mock(return_value=httpx.Response(200, json={"check_runs": []}))
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )

        service = GitHubService(token="test")
        result = await service.get_blame_board_data(
            "owner", "repo", pet_health=80, pet_mood="happy"
        )
        assert result.is_healthy is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_unhealthy_mood_returns_is_healthy_false(self) -> None:
        """A worried mood should yield is_healthy=False regardless of health %."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json={"default_branch": "main"})
        )
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[_make_commit("alice")])
        )
        respx.get(
            "https://api.github.com/repos/owner/repo/commits/sha_alice_0/check-runs"
        ).mock(return_value=httpx.Response(200, json={"check_runs": []}))
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )

        service = GitHubService(token="test")
        result = await service.get_blame_board_data(
            "owner", "repo", pet_health=80, pet_mood="worried"
        )
        assert result.is_healthy is False


class TestGetStalePrBlames:
    """Tests for _get_stale_pr_blames."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_reviewer_as_culprit(self) -> None:
        """Should blame a requested reviewer for a stale PR."""
        pr = _make_pr(1, "Add feature", days_old=3, reviewers=["bob"])
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[pr])
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            entries = await service._get_stale_pr_blames(client, "owner", "repo")

        assert len(entries) == 1
        assert entries[0].culprit == "bob"
        assert "review" in entries[0].issue.lower()

    @respx.mock
    @pytest.mark.asyncio
    async def test_blames_author_when_no_reviewer(self) -> None:
        """Should blame PR author when no reviewers are assigned."""
        pr = _make_pr(2, "Fix bug", days_old=4, reviewers=[], author="carol")
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[pr])
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            entries = await service._get_stale_pr_blames(client, "owner", "repo")

        assert len(entries) == 1
        assert entries[0].culprit == "carol"

    @respx.mock
    @pytest.mark.asyncio
    async def test_skips_fresh_prs(self) -> None:
        """PRs less than 48h old should not appear in blame."""
        pr = _make_pr(3, "New PR", days_old=0, reviewers=["dave"])
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[pr])
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            entries = await service._get_stale_pr_blames(client, "owner", "repo")

        assert entries == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_on_api_error(self) -> None:
        """Should return empty list on API error."""
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(500)
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            entries = await service._get_stale_pr_blames(client, "owner", "repo")

        assert entries == []


class TestGetTopCommitterHero:
    """Tests for _get_top_committer_hero."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_top_committer(self) -> None:
        """Should return the user with the most commits in 30d."""
        commits = [
            _make_commit("alice"),
            _make_commit("alice"),
            _make_commit("alice"),
            _make_commit("bob"),
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            hero = await service._get_top_committer_hero(client, "owner", "repo")

        assert hero is not None
        assert hero.hero == "alice"
        assert "3" in hero.good_deed

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_for_single_commit(self) -> None:
        """Should not credit someone for a single commit."""
        commits = [_make_commit("alice")]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            hero = await service._get_top_committer_hero(client, "owner", "repo")

        assert hero is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self) -> None:
        """Should return None on API error."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(500)
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            hero = await service._get_top_committer_hero(client, "owner", "repo")

        assert hero is None


class TestGetPrMergerHeroes:
    """Tests for _get_pr_merger_heroes."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_counts_merged_prs_per_merger(self) -> None:
        """Should count and return top PR mergers."""
        now = datetime.now(UTC)
        prs = [
            {
                "merged_at": (now - timedelta(days=1)).isoformat(),
                "merged_by": {"login": "alice"},
            },
            {
                "merged_at": (now - timedelta(days=2)).isoformat(),
                "merged_by": {"login": "alice"},
            },
            {
                "merged_at": (now - timedelta(days=3)).isoformat(),
                "merged_by": {"login": "bob"},
            },
        ]
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=prs)
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            heroes = await service._get_pr_merger_heroes(client, "owner", "repo")

        assert len(heroes) >= 1
        assert heroes[0].hero == "alice"
        assert "2" in heroes[0].good_deed

    @respx.mock
    @pytest.mark.asyncio
    async def test_ignores_old_merges(self) -> None:
        """Should ignore merges older than 30 days."""
        now = datetime.now(UTC)
        prs = [
            {
                "merged_at": (now - timedelta(days=40)).isoformat(),
                "merged_by": {"login": "alice"},
            },
        ]
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=prs)
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            heroes = await service._get_pr_merger_heroes(client, "owner", "repo")

        assert heroes == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_on_api_error(self) -> None:
        """Should return empty list on API error."""
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(500)
        )

        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            heroes = await service._get_pr_merger_heroes(client, "owner", "repo")

        assert heroes == []
