"""Tests for GitHub service."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from github_tamagotchi.services.github import GitHubService, RepoHealth


class TestGitHubServiceHeaders:
    """Tests for header generation."""

    def test_headers_without_token(self) -> None:
        """Headers should include Accept but no Authorization without token."""
        service = GitHubService(token=None)
        headers = service._get_headers()
        assert headers["Accept"] == "application/vnd.github.v3+json"
        assert "Authorization" not in headers

    def test_headers_with_token(self) -> None:
        """Headers should include Authorization when token is provided."""
        service = GitHubService(token="test-token")
        headers = service._get_headers()
        assert headers["Accept"] == "application/vnd.github.v3+json"
        assert headers["Authorization"] == "Bearer test-token"


class TestGetLastCommit:
    """Tests for fetching last commit."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_datetime_on_success(
        self,
        mock_commit_response: list[dict[str, Any]],
    ) -> None:
        """Should return datetime when commits are found."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=mock_commit_response)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_last_commit(client, "owner", "repo")

        assert result is not None
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_empty_commits(self) -> None:
        """Should return None when no commits exist."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[])
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_last_commit(client, "owner", "repo")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_error(self) -> None:
        """Should return None when API call fails."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_last_commit(client, "owner", "repo")

        assert result is None


class TestGetOpenPRs:
    """Tests for fetching open pull requests."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_prs_list(
        self,
        mock_prs_response: list[dict[str, Any]],
    ) -> None:
        """Should return list of PRs."""
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=mock_prs_response)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_open_prs(client, "owner", "repo")

        assert len(result) == 2
        assert result[0]["number"] == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        """Should return empty list when API call fails."""
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(500, json={"message": "Server Error"})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_open_prs(client, "owner", "repo")

        assert result == []


class TestGetOpenIssues:
    """Tests for fetching open issues."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_filters_out_pull_requests(
        self,
        mock_issues_response: list[dict[str, Any]],
    ) -> None:
        """Should filter out items that are pull requests."""
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=mock_issues_response)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_open_issues(client, "owner", "repo")

        # Original has 3 items, but one has pull_request key
        assert len(result) == 2
        for issue in result:
            assert "pull_request" not in issue

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        """Should return empty list when API call fails."""
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_open_issues(client, "owner", "repo")

        assert result == []


class TestGetCIStatus:
    """Tests for fetching CI status."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_true_on_success(
        self,
        mock_repo_response: dict[str, Any],
        mock_status_response_success: dict[str, Any],
    ) -> None:
        """Should return True when CI is successful."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=mock_repo_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/main/status").mock(
            return_value=httpx.Response(200, json=mock_status_response_success)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_ci_status(client, "owner", "repo")

        assert result is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_false_on_failure(
        self,
        mock_repo_response: dict[str, Any],
        mock_status_response_failure: dict[str, Any],
    ) -> None:
        """Should return False when CI has failed."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=mock_repo_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/main/status").mock(
            return_value=httpx.Response(200, json=mock_status_response_failure)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_ci_status(client, "owner", "repo")

        assert result is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_repo_error(self) -> None:
        """Should return None when repo fetch fails."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_ci_status(client, "owner", "repo")

        assert result is None


class TestAgeCalculations:
    """Tests for age calculation helpers."""

    def test_oldest_age_hours(self) -> None:
        """Should calculate age in hours correctly."""
        now = datetime.now(UTC)
        items = [
            {"created_at": (now).isoformat().replace("+00:00", "Z")},
            {"created_at": (now).isoformat().replace("+00:00", "Z")},
        ]
        service = GitHubService()
        age = service._get_oldest_age_hours(items)
        # Should be very close to 0 hours
        assert 0 <= age < 1

    def test_oldest_age_days(self) -> None:
        """Should calculate age in days correctly."""
        now = datetime.now(UTC)
        items = [
            {"created_at": (now).isoformat().replace("+00:00", "Z")},
        ]
        service = GitHubService()
        age = service._get_oldest_age_days(items)
        # Should be very close to 0 days
        assert 0 <= age < 1


class TestGetRepoHealth:
    """Tests for the main get_repo_health method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_repo_health_object(
        self,
        mock_commit_response: list[dict[str, Any]],
        mock_prs_response: list[dict[str, Any]],
        mock_issues_response: list[dict[str, Any]],
        mock_repo_response: dict[str, Any],
        mock_status_response_success: dict[str, Any],
    ) -> None:
        """Should return a complete RepoHealth object."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=mock_commit_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=mock_prs_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=mock_issues_response)
        )
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=mock_repo_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/main/status").mock(
            return_value=httpx.Response(200, json=mock_status_response_success)
        )

        service = GitHubService(token="test")
        result = await service.get_repo_health("owner", "repo")

        assert isinstance(result, RepoHealth)
        assert result.last_commit_at is not None
        assert result.open_prs_count == 2
        assert result.open_issues_count == 2  # 3 - 1 PR filtered
        assert result.last_ci_success is True
        assert result.has_stale_dependencies is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_handles_all_errors_gracefully(self) -> None:
        """Should return valid RepoHealth even when all API calls fail."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(500)
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(500)
        )
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(500)
        )
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(500)
        )

        service = GitHubService(token="test")
        result = await service.get_repo_health("owner", "repo")

        assert isinstance(result, RepoHealth)
        assert result.last_commit_at is None
        assert result.open_prs_count == 0
        assert result.open_issues_count == 0
        assert result.last_ci_success is None
