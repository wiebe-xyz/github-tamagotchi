"""Tests for GitHub service."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from github_tamagotchi.services.github import GitHubService, RateLimitError, RepoHealth


class TestRateLimitError:
    """Tests for RateLimitError exception."""

    def test_rate_limit_error_with_reset_time(self) -> None:
        """RateLimitError should store reset time."""
        reset_time = datetime.now(UTC)
        error = RateLimitError("Rate limit exceeded", reset_time=reset_time)
        assert str(error) == "Rate limit exceeded"
        assert error.reset_time == reset_time

    def test_rate_limit_error_without_reset_time(self) -> None:
        """RateLimitError should work without reset time."""
        error = RateLimitError("Rate limit exceeded")
        assert str(error) == "Rate limit exceeded"
        assert error.reset_time is None


class TestCheckRateLimit:
    """Tests for rate limit checking."""

    def test_does_not_raise_on_success(self) -> None:
        """Should not raise when response is successful."""
        service = GitHubService()
        response = httpx.Response(200)
        # Should not raise
        service._check_rate_limit(response)

    def test_does_not_raise_on_403_with_remaining(self) -> None:
        """Should not raise when 403 but rate limit has remaining calls."""
        service = GitHubService()
        response = httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "10"},
        )
        # Should not raise
        service._check_rate_limit(response)

    def test_raises_on_403_with_zero_remaining(self) -> None:
        """Should raise RateLimitError when rate limit is exhausted."""
        service = GitHubService()
        reset_timestamp = int(datetime.now(UTC).timestamp()) + 3600
        response = httpx.Response(
            403,
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(reset_timestamp),
            },
        )
        with pytest.raises(RateLimitError) as exc_info:
            service._check_rate_limit(response)
        assert exc_info.value.reset_time is not None

    def test_raises_on_403_zero_remaining_no_reset(self) -> None:
        """Should raise RateLimitError even without reset header."""
        service = GitHubService()
        response = httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0"},
        )
        with pytest.raises(RateLimitError) as exc_info:
            service._check_rate_limit(response)
        assert exc_info.value.reset_time is None


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

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError when rate limit is hit."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_last_commit(client, "owner", "repo")


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

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError when rate limit is hit."""
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_open_prs(client, "owner", "repo")


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
            return_value=httpx.Response(500, json={"message": "Server Error"})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_open_issues(client, "owner", "repo")

        assert result == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError when rate limit is hit."""
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_open_issues(client, "owner", "repo")


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

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error_on_repo_call(
        self, mock_status_response_success: dict[str, Any]
    ) -> None:
        """Should propagate RateLimitError when rate limit is hit on repo call."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_ci_status(client, "owner", "repo")

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error_on_status_call(
        self, mock_repo_response: dict[str, Any]
    ) -> None:
        """Should propagate RateLimitError when rate limit is hit on status call."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=mock_repo_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/main/status").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_ci_status(client, "owner", "repo")


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


class TestGetSecurityAlerts:
    """Tests for fetching Dependabot security alerts."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_counts_by_severity(
        self, mock_security_alerts_response: list[dict[str, Any]]
    ) -> None:
        """Should return alert counts grouped by severity."""
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(200, json=mock_security_alerts_response)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_security_alerts(client, "owner", "repo")

        assert result["critical"] == 1
        assert result["high"] == 1
        assert result["medium"] == 1
        assert result["low"] == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zeros_when_no_alerts(
        self, mock_security_alerts_empty: list[dict[str, Any]]
    ) -> None:
        """Should return all zeros when there are no open alerts."""
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(200, json=mock_security_alerts_empty)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_security_alerts(client, "owner", "repo")

        assert result == {"critical": 0, "high": 0, "medium": 0, "low": 0}

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zeros_on_404(self) -> None:
        """Should return zeros when Dependabot is not enabled (404)."""
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_security_alerts(client, "owner", "repo")

        assert result == {"critical": 0, "high": 0, "medium": 0, "low": 0}

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zeros_on_error(self) -> None:
        """Should return zeros when API call fails."""
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_security_alerts(client, "owner", "repo")

        assert result == {"critical": 0, "high": 0, "medium": 0, "low": 0}

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError when rate limit is hit."""
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_security_alerts(client, "owner", "repo")

    @respx.mock
    @pytest.mark.asyncio
    async def test_counts_multiple_alerts_per_severity(self) -> None:
        """Should count multiple alerts of the same severity correctly."""
        alerts = [
            {"number": i, "state": "open", "security_advisory": {"severity": "critical"}}
            for i in range(1, 4)
        ]
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(200, json=alerts)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_security_alerts(client, "owner", "repo")

        assert result["critical"] == 3
        assert result["high"] == 0


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
        mock_security_alerts_empty: list[dict[str, Any]],
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
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(200, json=mock_security_alerts_empty)
        )

        service = GitHubService(token="test")
        result = await service.get_repo_health("owner", "repo")

        assert isinstance(result, RepoHealth)
        assert result.last_commit_at is not None
        assert result.open_prs_count == 2
        assert result.open_issues_count == 2  # 3 - 1 PR filtered
        assert result.last_ci_success is True
        assert result.has_stale_dependencies is False
        assert result.security_alerts_critical == 0
        assert result.security_alerts_high == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_security_alert_counts(
        self,
        mock_commit_response: list[dict[str, Any]],
        mock_prs_response: list[dict[str, Any]],
        mock_issues_response: list[dict[str, Any]],
        mock_repo_response: dict[str, Any],
        mock_status_response_success: dict[str, Any],
        mock_security_alerts_response: list[dict[str, Any]],
    ) -> None:
        """Should include security alert counts in RepoHealth."""
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
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(200, json=mock_security_alerts_response)
        )

        service = GitHubService(token="test")
        result = await service.get_repo_health("owner", "repo")

        assert result.security_alerts_critical == 1
        assert result.security_alerts_high == 1
        assert result.security_alerts_medium == 1
        assert result.security_alerts_low == 1

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
        respx.get("https://api.github.com/repos/owner/repo").mock(return_value=httpx.Response(500))
        respx.get("https://api.github.com/repos/owner/repo/releases").mock(
            return_value=httpx.Response(500)
        )
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(500)
        )

        service = GitHubService(token="test")
        result = await service.get_repo_health("owner", "repo")

        assert isinstance(result, RepoHealth)
        assert result.last_commit_at is None
        assert result.open_prs_count == 0
        assert result.open_issues_count == 0
        assert result.last_ci_success is None
        assert result.release_count_30d == 0
        assert result.contributor_count == 0
        assert result.security_alerts_critical == 0
        assert result.security_alerts_high == 0


class TestGetReleaseCount30d:
    """Tests for fetching release count in last 30 days."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_counts_recent_releases(self) -> None:
        """Should count only releases published in the last 30 days."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        releases = [
            {"published_at": (now - timedelta(days=5)).isoformat()},   # within 30d
            {"published_at": (now - timedelta(days=15)).isoformat()},  # within 30d
            {"published_at": (now - timedelta(days=40)).isoformat()},  # older than 30d
        ]
        respx.get("https://api.github.com/repos/owner/repo/releases").mock(
            return_value=httpx.Response(200, json=releases)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_release_count_30d(client, "owner", "repo")

        assert result == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_caps_at_ten(self) -> None:
        """Should cap result at 10 regardless of actual count."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        releases = [
            {"published_at": (now - timedelta(days=i)).isoformat()} for i in range(1, 16)
        ]
        respx.get("https://api.github.com/repos/owner/repo/releases").mock(
            return_value=httpx.Response(200, json=releases)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_release_count_30d(client, "owner", "repo")

        assert result == 10

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zero_on_api_error(self) -> None:
        """Should return 0 when the releases API returns an error."""
        respx.get("https://api.github.com/repos/owner/repo/releases").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_release_count_30d(client, "owner", "repo")

        assert result == 0


class TestGetContributorCount90d:
    """Tests for fetching unique contributor count in last 90 days."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_counts_unique_authors(self) -> None:
        """Should count unique author logins from commits."""
        commits = [
            {"author": {"login": "alice"}},
            {"author": {"login": "bob"}},
            {"author": {"login": "alice"}},  # duplicate, should not count twice
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_contributor_count_90d(client, "owner", "repo")

        assert result == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_caps_at_twenty(self) -> None:
        """Should cap result at 20 regardless of actual count."""
        commits = [{"author": {"login": f"user{i}"}} for i in range(25)]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_contributor_count_90d(client, "owner", "repo")

        assert result == 20

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zero_on_api_error(self) -> None:
        """Should return 0 when the commits API returns an error."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_contributor_count_90d(client, "owner", "repo")

        assert result == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_skips_commits_without_author(self) -> None:
        """Should skip commits where author or login is missing."""
        commits = [
            {"author": {"login": "alice"}},
            {"author": None},
            {},
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_contributor_count_90d(client, "owner", "repo")

        assert result == 1


class TestGetDependentCount:
    """Tests for _get_dependent_count method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_count_from_html(self) -> None:
        """Should parse dependent count from GitHub network/dependents page."""
        html = (
            "<html><body>"
            '<a href="/owner/repo/network/dependents?dependent_type=REPOSITORY">'
            "1,234 Repositories"
            "</a></body></html>"
        )
        respx.get("https://github.com/owner/repo/network/dependents").mock(
            return_value=httpx.Response(200, text=html)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_dependent_count(client, "owner", "repo")

        assert result == 1234

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_count_without_comma(self) -> None:
        """Should handle counts without comma separators."""
        html = "<html><body>42 Repositories</body></html>"
        respx.get("https://github.com/owner/repo/network/dependents").mock(
            return_value=httpx.Response(200, text=html)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_dependent_count(client, "owner", "repo")

        assert result == 42

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zero_on_404(self) -> None:
        """Should return 0 when page is not found."""
        respx.get("https://github.com/owner/repo/network/dependents").mock(
            return_value=httpx.Response(404)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_dependent_count(client, "owner", "repo")

        assert result == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_match(self) -> None:
        """Should return 0 when page has no recognisable count."""
        respx.get("https://github.com/owner/repo/network/dependents").mock(
            return_value=httpx.Response(200, text="<html><body>No dependents</body></html>")
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_dependent_count(client, "owner", "repo")

        assert result == 0


class TestGetStarForkCounts:
    """Tests for _get_star_fork_counts method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_star_and_fork_counts(self) -> None:
        """Should return star and fork counts from repo data."""
        repo_data = {
            "id": 12345,
            "name": "test-repo",
            "stargazers_count": 150,
            "forks_count": 42,
        }
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=repo_data)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            stars, forks = await service._get_star_fork_counts(client, "owner", "repo")

        assert stars == 150
        assert forks == 42

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zeros_on_error(self) -> None:
        """Should return (0, 0) when API call fails."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            stars, forks = await service._get_star_fork_counts(client, "owner", "repo")

        assert stars == 0
        assert forks == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_defaults_to_zero_when_keys_missing(self) -> None:
        """Should default to 0 when stargazers_count or forks_count keys are absent."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json={"id": 1, "name": "repo"})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            stars, forks = await service._get_star_fork_counts(client, "owner", "repo")

        assert stars == 0
        assert forks == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError when rate limit is hit."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_star_fork_counts(client, "owner", "repo")


class TestGetRepoHealthStarFork:
    """Tests that get_repo_health correctly includes star and fork counts."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_includes_star_and_fork_counts(
        self,
        mock_commit_response: list[dict[str, Any]],
        mock_prs_response: list[dict[str, Any]],
        mock_issues_response: list[dict[str, Any]],
        mock_status_response_success: dict[str, Any],
        mock_security_alerts_empty: list[dict[str, Any]],
    ) -> None:
        """RepoHealth should contain star and fork counts."""
        repo_data = {
            "id": 12345,
            "name": "test-repo",
            "full_name": "owner/test-repo",
            "default_branch": "main",
            "stargazers_count": 99,
            "forks_count": 7,
        }
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
            return_value=httpx.Response(200, json=repo_data)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/main/status").mock(
            return_value=httpx.Response(200, json=mock_status_response_success)
        )
        respx.get("https://api.github.com/repos/owner/repo/releases").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://api.github.com/repos/owner/repo/dependabot/alerts").mock(
            return_value=httpx.Response(200, json=mock_security_alerts_empty)
        )
        respx.get("https://github.com/owner/repo/network/dependents").mock(
            return_value=httpx.Response(200, text="<html><body>10 Repositories</body></html>")
        )

        service = GitHubService(token="test")
        result = await service.get_repo_health("owner", "repo")

        assert result.star_count == 99
        assert result.fork_count == 7
        assert result.dependent_count == 10


class TestGetContributorStats:
    """Tests for get_contributor_stats method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_stats_for_active_contributor(self) -> None:
        """Should return correct stats when user has recent commits."""
        from datetime import timedelta

        now = datetime.now(UTC)
        recent_date = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        user_commits = [
            {
                "sha": "abc123",
                "author": {"login": "alice"},
                "commit": {"committer": {"date": recent_date}},
            }
        ]
        all_commits = [
            {"sha": "abc123", "author": {"login": "alice"}},
            {"sha": "def456", "author": {"login": "bob"}},
        ]
        # Both calls go to same URL with different params — respx matches by URL only
        # so we use a side_effect approach with a counter
        call_count = 0

        def commit_side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "author=alice" in str(request.url):
                return httpx.Response(200, json=user_commits)
            return httpx.Response(200, json=all_commits)

        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            side_effect=commit_side_effect
        )
        # CI check for the latest commit sha
        respx.get("https://api.github.com/repos/owner/repo/commits/abc123/check-runs").mock(
            return_value=httpx.Response(200, json={"check_runs": []})
        )

        service = GitHubService(token="test")
        result = await service.get_contributor_stats("owner", "repo", "alice")

        assert result.commits_30d == 1
        assert result.last_commit_at is not None
        assert result.days_since_last_commit is not None
        assert result.days_since_last_commit >= 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_zero_commits_for_inactive_contributor(self) -> None:
        """Should look up historical commit when no recent commits found."""
        from datetime import timedelta

        old_date = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_commits = [
            {
                "sha": "old123",
                "author": {"login": "alice"},
                "commit": {"committer": {"date": old_date}},
            }
        ]
        call_count = 0

        def commit_side_effect(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(request.url)
            # _fetch_commits_parallel makes two calls: one with author=alice (user commits)
            # and one without (all commits). Then _get_user_last_commit makes a third call
            # with author=alice&per_page=1 (no since param).
            if "author=alice" in url and "per_page=1" in url and "since" not in url:
                return httpx.Response(200, json=old_commits)  # historical lookup
            if "author=alice" in url:
                return httpx.Response(200, json=[])  # no recent user commits
            return httpx.Response(200, json=[])  # no all-repo commits either

        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            side_effect=commit_side_effect
        )

        service = GitHubService(token="test")
        result = await service.get_contributor_stats("owner", "repo", "alice")

        assert result.commits_30d == 0
        assert result.last_commit_at is not None  # found via historical lookup

    @respx.mock
    @pytest.mark.asyncio
    async def test_is_top_contributor_when_has_most_commits(self) -> None:
        """Should mark contributor as top when they have the most commits."""
        from datetime import timedelta

        recent_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        user_commits = [
            {"sha": f"sha{i}", "author": {"login": "alice"}, "commit": {"committer": {"date": recent_date}}}  # noqa: E501
            for i in range(5)
        ]
        all_commits = (
            [{"sha": f"sha{i}", "author": {"login": "alice"}} for i in range(5)]
            + [{"sha": f"othsha{i}", "author": {"login": "bob"}} for i in range(2)]
        )

        def commit_side_effect(request: httpx.Request) -> httpx.Response:
            if "author=alice" in str(request.url):
                return httpx.Response(200, json=user_commits)
            return httpx.Response(200, json=all_commits)

        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            side_effect=commit_side_effect
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/sha0/check-runs").mock(
            return_value=httpx.Response(200, json={"check_runs": []})
        )

        service = GitHubService(token="test")
        result = await service.get_contributor_stats("owner", "repo", "alice")

        assert result.is_top_contributor is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_has_failed_ci_when_commit_check_fails(self) -> None:
        """Should detect failed CI on the contributor's latest commit."""
        from datetime import timedelta

        recent_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        user_commits = [
            {
                "sha": "failsha",
                "author": {"login": "alice"},
                "commit": {"committer": {"date": recent_date}},
            }
        ]

        def commit_side_effect(request: httpx.Request) -> httpx.Response:
            if "author=alice" in str(request.url):
                return httpx.Response(200, json=user_commits)
            return httpx.Response(200, json=user_commits)

        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            side_effect=commit_side_effect
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/failsha/check-runs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "check_runs": [
                        {"conclusion": "failure", "status": "completed", "name": "test"}
                    ]
                },
            )
        )

        service = GitHubService(token="test")
        result = await service.get_contributor_stats("owner", "repo", "alice")

        assert result.has_failed_ci is True


class TestFetchCommitsParallel:
    """Tests for _fetch_commits_parallel helper."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_both_user_and_all_commits(self) -> None:
        """Should return user commits and all commits as a tuple."""
        user_commits = [{"sha": "u1", "author": {"login": "alice"}}]
        all_commits = [
            {"sha": "u1", "author": {"login": "alice"}},
            {"sha": "a2", "author": {"login": "bob"}},
        ]

        def side_effect(request: httpx.Request) -> httpx.Response:
            if "author=alice" in str(request.url):
                return httpx.Response(200, json=user_commits)
            return httpx.Response(200, json=all_commits)

        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            side_effect=side_effect
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            u, a = await service._fetch_commits_parallel(
                client, "owner", "repo", "alice", "2024-01-01T00:00:00"
            )

        assert len(u) == 1
        assert len(a) == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_lists_on_error(self) -> None:
        """Should return empty lists when API call fails."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            u, a = await service._fetch_commits_parallel(
                client, "owner", "repo", "alice", "2024-01-01T00:00:00"
            )

        assert u == []
        assert a == []


class TestGetUserLastCommit:
    """Tests for _get_user_last_commit helper."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_datetime_when_found(self) -> None:
        """Should return datetime of user's last commit."""
        commits = [
            {
                "sha": "abc",
                "commit": {"committer": {"date": "2025-03-01T10:00:00Z"}},
            }
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_user_last_commit(client, "owner", "repo", "alice")

        assert result is not None
        assert result.year == 2025

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_when_no_commits(self) -> None:
        """Should return None when user has no commits."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[])
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_user_last_commit(client, "owner", "repo", "alice")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_error(self) -> None:
        """Should return None on API error."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_user_last_commit(client, "owner", "repo", "alice")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_user_last_commit(client, "owner", "repo", "alice")


class TestHasFailedCi:
    """Tests for _has_failed_ci method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_false_when_no_runs(self) -> None:
        """Should return False when there are no check runs."""
        respx.get("https://api.github.com/repos/owner/repo/commits/sha123/check-runs").mock(
            return_value=httpx.Response(200, json={"check_runs": []})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._has_failed_ci(client, "owner", "repo", "sha123")

        assert result is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_true_when_failure(self) -> None:
        """Should return True when at least one run failed."""
        runs = [
            {"conclusion": "failure", "status": "completed"},
            {"conclusion": "success", "status": "completed"},
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits/sha123/check-runs").mock(
            return_value=httpx.Response(200, json={"check_runs": runs})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._has_failed_ci(client, "owner", "repo", "sha123")

        assert result is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_true_when_timed_out(self) -> None:
        """Should return True when a run timed out."""
        runs = [{"conclusion": "timed_out", "status": "completed"}]
        respx.get("https://api.github.com/repos/owner/repo/commits/sha123/check-runs").mock(
            return_value=httpx.Response(200, json={"check_runs": runs})
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._has_failed_ci(client, "owner", "repo", "sha123")

        assert result is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_false_on_error(self) -> None:
        """Should return False on API error."""
        respx.get("https://api.github.com/repos/owner/repo/commits/sha123/check-runs").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._has_failed_ci(client, "owner", "repo", "sha123")

        assert result is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError."""
        respx.get("https://api.github.com/repos/owner/repo/commits/sha123/check-runs").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._has_failed_ci(client, "owner", "repo", "sha123")


class TestGetAllContributorActivity:
    """Tests for get_all_contributor_activity method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_commits_by_user(self) -> None:
        """Should aggregate commit counts per user."""
        d1, d2, d3 = "2025-03-01T10:00:00Z", "2025-03-02T10:00:00Z", "2025-03-03T10:00:00Z"
        commits = [
            {"sha": "s1", "author": {"login": "alice"}, "commit": {"committer": {"date": d1}}},
            {"sha": "s2", "author": {"login": "alice"}, "commit": {"committer": {"date": d2}}},
            {"sha": "s3", "author": {"login": "bob"}, "commit": {"committer": {"date": d3}}},
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )
        service = GitHubService(token="test")
        result = await service.get_all_contributor_activity("owner", "repo")

        assert result.commits_by_user["alice"] == 2
        assert result.commits_by_user["bob"] == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_merged_prs_by_user(self) -> None:
        """Should count recently merged PRs per user."""
        from datetime import timedelta

        recent_merge = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old_merge = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        prs = [
            {"merged_at": recent_merge, "merged_by": {"login": "alice"}},
            {"merged_at": recent_merge, "merged_by": {"login": "alice"}},
            {"merged_at": old_merge, "merged_by": {"login": "alice"}},  # too old
            {"merged_at": None, "merged_by": {"login": "bob"}},  # not merged
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=prs)
        )
        service = GitHubService(token="test")
        result = await service.get_all_contributor_activity("owner", "repo")

        assert result.merged_prs_by_user.get("alice") == 2
        assert "bob" not in result.merged_prs_by_user

    @respx.mock
    @pytest.mark.asyncio
    async def test_skips_commits_without_author_login(self) -> None:
        """Should skip commits missing author or login."""
        commits = [
            {"sha": "s1", "author": None, "commit": {"committer": {"date": "2025-03-01T10:00:00Z"}}},  # noqa: E501
            {"sha": "s2", "commit": {"committer": {"date": "2025-03-02T10:00:00Z"}}},
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )
        service = GitHubService(token="test")
        result = await service.get_all_contributor_activity("owner", "repo")

        assert result.commits_by_user == {}

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_on_commits(self) -> None:
        """Should propagate RateLimitError from commits API."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        with pytest.raises(RateLimitError):
            await service.get_all_contributor_activity("owner", "repo")


class TestGetWeeklyCommits30d:
    """Tests for _get_weekly_commits_30d method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_four_weekly_buckets(self) -> None:
        """Should return exactly 4 weekly buckets."""
        from datetime import timedelta

        now = datetime.now(UTC)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        commits = [
            {"sha": f"sha{i}", "commit": {"committer": {"date": (now - timedelta(days=i)).strftime(fmt)}}}  # noqa: E501
            for i in range(1, 8)
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            buckets, total = await service._get_weekly_commits_30d(client, "owner", "repo")

        assert len(buckets) == 4
        assert total == 7

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_buckets_on_error(self) -> None:
        """Should return 4 zero-count buckets on error."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            buckets, total = await service._get_weekly_commits_30d(client, "owner", "repo")

        assert len(buckets) == 4
        assert all(b.count == 0 for b in buckets)
        assert total == 0


class TestGetAvgPrMergeHours:
    """Tests for _get_avg_pr_merge_hours method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_avg_merge_hours(self) -> None:
        """Should compute average merge time in hours."""
        prs = [
            {
                "created_at": "2025-01-01T00:00:00Z",
                "merged_at": "2025-01-01T02:00:00Z",  # 2 hours
            },
            {
                "created_at": "2025-01-02T00:00:00Z",
                "merged_at": "2025-01-02T06:00:00Z",  # 6 hours
            },
        ]
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=prs)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_avg_pr_merge_hours(client, "owner", "repo")

        assert result == pytest.approx(4.0)

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_when_no_merged_prs(self) -> None:
        """Should return None when no PRs have merged_at."""
        prs = [{"created_at": "2025-01-01T00:00:00Z", "merged_at": None}]
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=prs)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_avg_pr_merge_hours(client, "owner", "repo")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self) -> None:
        """Should return None on API error."""
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_avg_pr_merge_hours(client, "owner", "repo")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError."""
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            with pytest.raises(RateLimitError):
                await service._get_avg_pr_merge_hours(client, "owner", "repo")


class TestGetAvgIssueResponseHours:
    """Tests for _get_avg_issue_response_hours method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_avg_response_time(self) -> None:
        """Should compute average response time from issue creation to first comment."""
        issues = [
            {
                "number": 1,
                "created_at": "2025-01-01T00:00:00Z",
                "comments": 1,
                "state": "open",
            }
        ]
        comments = [{"created_at": "2025-01-01T04:00:00Z", "body": "reply"}]
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=issues)
        )
        respx.get("https://api.github.com/repos/owner/repo/issues/1/comments").mock(
            return_value=httpx.Response(200, json=comments)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_avg_issue_response_hours(client, "owner", "repo")

        assert result == pytest.approx(4.0)

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_when_no_issues_with_comments(self) -> None:
        """Should return None when no issues have any comments."""
        issues = [{"number": 1, "created_at": "2025-01-01T00:00:00Z", "comments": 0}]
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=issues)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_avg_issue_response_hours(client, "owner", "repo")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self) -> None:
        """Should return None on API error."""
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_avg_issue_response_hours(client, "owner", "repo")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_filters_out_pull_requests_from_issues(self) -> None:
        """Should filter out PRs before computing response time."""
        issues = [
            {
                "number": 1,
                "created_at": "2025-01-01T00:00:00Z",
                "comments": 1,
                "pull_request": {"url": "https://..."},
            }
        ]
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=issues)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            result = await service._get_avg_issue_response_hours(client, "owner", "repo")

        assert result is None


class TestGetCiPassRate:
    """Tests for _get_ci_pass_rate method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_pass_rate(self, mock_repo_response: dict[str, Any]) -> None:
        """Should compute pass rate from recent check runs."""
        commits = [{"sha": "s1"}, {"sha": "s2"}]
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=mock_repo_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/s1/check-runs").mock(
            return_value=httpx.Response(
                200, json={"check_runs": [{"conclusion": "success", "status": "completed"}]}
            )
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/s2/check-runs").mock(
            return_value=httpx.Response(
                200, json={"check_runs": [{"conclusion": "failure", "status": "completed"}]}
            )
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            rate, count = await service._get_ci_pass_rate(client, "owner", "repo")

        assert rate == pytest.approx(0.5)
        assert count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_when_no_commits(self, mock_repo_response: dict[str, Any]) -> None:
        """Should return (None, 0) when no commits."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=mock_repo_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[])
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            rate, count = await service._get_ci_pass_rate(client, "owner", "repo")

        assert rate is None
        assert count == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_repo_error(self) -> None:
        """Should return (None, 0) when repo lookup fails."""
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        async with httpx.AsyncClient() as client:
            rate, count = await service._get_ci_pass_rate(client, "owner", "repo")

        assert rate is None
        assert count == 0


class TestGetRepoInsights:
    """Tests for get_repo_insights method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_repo_insights_object(
        self, mock_repo_response: dict[str, Any]
    ) -> None:
        """Should return a complete RepoInsights object."""
        from github_tamagotchi.services.github import RepoInsights

        commits = [
            {"sha": "sha1", "commit": {"committer": {"date": "2025-03-01T10:00:00Z"}}}
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://api.github.com/repos/owner/repo/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=mock_repo_response)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/sha1/check-runs").mock(
            return_value=httpx.Response(200, json={"check_runs": []})
        )

        service = GitHubService(token="test")
        result = await service.get_repo_insights("owner", "repo")

        assert isinstance(result, RepoInsights)
        assert len(result.weekly_commits) == 4
        assert result.open_prs_count == 0


class TestListUserRepos:
    """Tests for list_user_repos method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_list_of_repos(self) -> None:
        """Should return list of repository data."""
        repos = [{"id": 1, "name": "repo1"}, {"id": 2, "name": "repo2"}]
        respx.get("https://api.github.com/user/repos").mock(
            return_value=httpx.Response(200, json=repos)
        )
        service = GitHubService(token="test")
        result = await service.list_user_repos()

        assert len(result) == 2
        assert result[0]["name"] == "repo1"

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        """Should return empty list on API error."""
        respx.get("https://api.github.com/user/repos").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        result = await service.list_user_repos()

        assert result == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError."""
        respx.get("https://api.github.com/user/repos").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        with pytest.raises(RateLimitError):
            await service.list_user_repos()


class TestGetTopContributor:
    """Tests for get_top_contributor method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_top_committer(self) -> None:
        """Should return login of user with most commits."""
        commits = [
            {"sha": "s1", "author": {"login": "alice"}},
            {"sha": "s2", "author": {"login": "alice"}},
            {"sha": "s3", "author": {"login": "bob"}},
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        service = GitHubService(token="test")
        result = await service.get_top_contributor("owner", "repo")

        assert result == "alice"

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_when_no_commits(self) -> None:
        """Should return None when no commits found."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=[])
        )
        service = GitHubService(token="test")
        result = await service.get_top_contributor("owner", "repo")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_error(self) -> None:
        """Should return None on API error."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        result = await service.get_top_contributor("owner", "repo")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError."""
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        with pytest.raises(RateLimitError):
            await service.get_top_contributor("owner", "repo")

    @respx.mock
    @pytest.mark.asyncio
    async def test_skips_commits_without_author(self) -> None:
        """Should skip commits with no author login."""
        commits = [
            {"sha": "s1", "author": None},
            {"sha": "s2", "author": {"login": "bob"}},
        ]
        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        service = GitHubService(token="test")
        result = await service.get_top_contributor("owner", "repo")

        assert result == "bob"


class TestGetRepoPermission:
    """Tests for get_repo_permission method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_permission_level(self) -> None:
        """Should return the permission string."""
        respx.get("https://api.github.com/repos/owner/repo/collaborators/alice/permission").mock(
            return_value=httpx.Response(200, json={"permission": "write"})
        )
        service = GitHubService(token="test")
        result = await service.get_repo_permission("owner", "repo", "alice")

        assert result == "write"

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_404_returns_none(self) -> None:
        """Should return 'none' when user is not a collaborator."""
        respx.get("https://api.github.com/repos/owner/repo/collaborators/unknown/permission").mock(
            return_value=httpx.Response(404)
        )
        service = GitHubService(token="test")
        result = await service.get_repo_permission("owner", "repo", "unknown")

        assert result == "none"

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_none_on_error(self) -> None:
        """Should return None on API error."""
        respx.get("https://api.github.com/repos/owner/repo/collaborators/alice/permission").mock(
            return_value=httpx.Response(500)
        )
        service = GitHubService(token="test")
        result = await service.get_repo_permission("owner", "repo", "alice")

        assert result is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_rate_limit_error(self) -> None:
        """Should propagate RateLimitError."""
        respx.get("https://api.github.com/repos/owner/repo/collaborators/alice/permission").mock(
            return_value=httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}
            )
        )
        service = GitHubService(token="test")
        with pytest.raises(RateLimitError):
            await service.get_repo_permission("owner", "repo", "alice")


class TestFormatDurationAndWhen:
    """Tests for _format_duration and _format_when helpers."""

    def test_format_duration_just_now(self) -> None:
        """Should return 'just now' for very recent datetimes."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(minutes=30)
        assert service._format_duration(dt) == "just now"

    def test_format_duration_hours(self) -> None:
        """Should return hours string for same-day events."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(hours=5)
        assert "hours" in service._format_duration(dt)

    def test_format_duration_one_day(self) -> None:
        """Should return '1 day' for ~24 hours ago."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(hours=25)
        assert service._format_duration(dt) == "1 day"

    def test_format_duration_multiple_days(self) -> None:
        """Should return 'N days' for multi-day events."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(days=5)
        result = service._format_duration(dt)
        assert "days" in result

    def test_format_when_today(self) -> None:
        """Should return 'Today' for events within the last 24 hours."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(hours=1)
        assert service._format_when(dt) == "Today"

    def test_format_when_yesterday(self) -> None:
        """Should return 'Yesterday' for events 24-48 hours ago."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(hours=36)
        assert service._format_when(dt) == "Yesterday"

    def test_format_when_this_week(self) -> None:
        """Should return 'This week' for events 2-7 days ago."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(days=4)
        assert service._format_when(dt) == "This week"

    def test_format_when_days_ago(self) -> None:
        """Should return 'N days ago' for events more than 7 days ago."""
        from datetime import timedelta

        service = GitHubService()
        dt = datetime.now(UTC) - timedelta(days=10)
        result = service._format_when(dt)
        assert "days ago" in result


class TestGetBlameBoardData:
    """Tests for get_blame_board_data method."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_hero_entries_when_healthy(self) -> None:
        """Should return hero entries when pet is healthy."""
        from datetime import timedelta

        from github_tamagotchi.services.github import BlameBoardData

        since = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        commits = [
            {"sha": "sha1", "author": {"login": "alice"}, "commit": {"committer": {"date": since}}},
            {"sha": "sha1", "author": {"login": "alice"}, "commit": {"committer": {"date": since}}},
            {"sha": "sha2", "author": {"login": "alice"}, "commit": {"committer": {"date": since}}},
        ]
        repo_data = {"id": 1, "name": "repo", "default_branch": "main"}
        check_runs = {"check_runs": [{"conclusion": "success", "status": "completed"}]}

        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=[])
        )
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=repo_data)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/sha1/check-runs").mock(
            return_value=httpx.Response(200, json=check_runs)
        )

        service = GitHubService(token="test")
        result = await service.get_blame_board_data(
            "owner", "repo", pet_health=80, pet_mood="happy"
        )

        assert isinstance(result, BlameBoardData)
        assert result.is_healthy is True
        assert result.blame_entries == []

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_blame_entries_when_unhealthy(self) -> None:
        """Should return blame entries when pet is unhealthy."""
        from datetime import timedelta

        from github_tamagotchi.services.github import BlameBoardData

        old_pr_date = (datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        prs = [
            {
                "number": 1,
                "title": "My old PR",
                "created_at": old_pr_date,
                "requested_reviewers": [{"login": "bob"}],
                "user": {"login": "alice"},
            }
        ]
        repo_data = {"id": 1, "name": "repo", "default_branch": "main"}
        commits = [{"sha": "sha1", "author": {"login": "alice"}, "commit": {"committer": {"date": old_pr_date}}}]  # noqa: E501

        respx.get("https://api.github.com/repos/owner/repo/commits").mock(
            return_value=httpx.Response(200, json=commits)
        )
        respx.get("https://api.github.com/repos/owner/repo/pulls").mock(
            return_value=httpx.Response(200, json=prs)
        )
        respx.get("https://api.github.com/repos/owner/repo").mock(
            return_value=httpx.Response(200, json=repo_data)
        )
        respx.get("https://api.github.com/repos/owner/repo/commits/sha1/check-runs").mock(
            return_value=httpx.Response(200, json={"check_runs": []})
        )

        service = GitHubService(token="test")
        result = await service.get_blame_board_data("owner", "repo", pet_health=20, pet_mood="sick")

        assert isinstance(result, BlameBoardData)
        assert result.is_healthy is False
        assert result.hero_entries == []
