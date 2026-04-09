"""GitHub API service for repository health metrics."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from github_tamagotchi.core.config import settings

logger = structlog.get_logger()


class RateLimitError(Exception):
    """Raised when GitHub API rate limit is exceeded."""

    def __init__(self, message: str, reset_time: datetime | None = None) -> None:
        super().__init__(message)
        self.reset_time = reset_time


@dataclass
class RepoHealth:
    """Health metrics for a GitHub repository."""

    last_commit_at: datetime | None
    open_prs_count: int
    oldest_pr_age_hours: float | None
    open_issues_count: int
    oldest_issue_age_days: float | None
    last_ci_success: bool | None
    has_stale_dependencies: bool
    release_count_30d: int = field(default=0)
    contributor_count: int = field(default=0)


class GitHubService:
    """Service for fetching GitHub repository health metrics."""

    def __init__(self, token: str | None = None) -> None:
        """Initialize with optional GitHub token."""
        self.token = token or settings.github_token
        self.base_url = "https://api.github.com"

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with authentication."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _check_rate_limit(self, response: httpx.Response) -> None:
        """Check if rate limit was hit and raise RateLimitError if so."""
        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining is not None and int(remaining) == 0:
                reset_timestamp = response.headers.get("X-RateLimit-Reset")
                reset_time = None
                if reset_timestamp:
                    reset_time = datetime.fromtimestamp(int(reset_timestamp), tz=UTC)
                raise RateLimitError(
                    "GitHub API rate limit exceeded",
                    reset_time=reset_time,
                )

    async def get_repo_health(self, owner: str, repo: str) -> RepoHealth:
        """Fetch health metrics for a repository."""
        async with httpx.AsyncClient() as client:
            # Get last commit
            last_commit_at = await self._get_last_commit(client, owner, repo)

            # Get open PRs
            prs = await self._get_open_prs(client, owner, repo)
            open_prs_count = len(prs)
            oldest_pr_age = self._get_oldest_age_hours(prs) if prs else None

            # Get open issues
            issues = await self._get_open_issues(client, owner, repo)
            open_issues_count = len(issues)
            oldest_issue_age = self._get_oldest_age_days(issues) if issues else None

            # Get CI status
            last_ci_success = await self._get_ci_status(client, owner, repo)

            # Get release frequency (last 30 days)
            release_count_30d = await self._get_release_count_30d(client, owner, repo)

            # Get contributor count (last 90 days)
            contributor_count = await self._get_contributor_count_90d(client, owner, repo)

            return RepoHealth(
                last_commit_at=last_commit_at,
                open_prs_count=open_prs_count,
                oldest_pr_age_hours=oldest_pr_age,
                open_issues_count=open_issues_count,
                oldest_issue_age_days=oldest_issue_age,
                last_ci_success=last_ci_success,
                has_stale_dependencies=False,  # TODO: Check dependabot
                release_count_30d=release_count_30d,
                contributor_count=contributor_count,
            )

    async def _get_last_commit(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> datetime | None:
        """Get the timestamp of the last commit."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"per_page": 1},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits = resp.json()
            if commits:
                return datetime.fromisoformat(
                    commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00")
                )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get last commit", error=str(e))
        return None

    async def _get_open_prs(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> list[dict[str, Any]]:
        """Get list of open pull requests."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/pulls",
                headers=self._get_headers(),
                params={"state": "open", "per_page": 100},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            result: list[dict[str, Any]] = resp.json()
            return result
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get open PRs", error=str(e))
        return []

    async def _get_open_issues(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> list[dict[str, Any]]:
        """Get list of open issues (excluding PRs)."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/issues",
                headers=self._get_headers(),
                params={"state": "open", "per_page": 100},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            # Filter out PRs (they appear in issues endpoint too)
            data: list[dict[str, Any]] = resp.json()
            return [i for i in data if "pull_request" not in i]
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get open issues", error=str(e))
        return []

    async def _get_ci_status(self, client: httpx.AsyncClient, owner: str, repo: str) -> bool | None:
        """Get the CI status of the default branch."""
        try:
            # Get default branch
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}",
                headers=self._get_headers(),
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            repo_data: dict[str, Any] = resp.json()
            default_branch: str = repo_data["default_branch"]

            # Get combined status
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits/{default_branch}/status",
                headers=self._get_headers(),
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            status: dict[str, Any] = resp.json()
            return bool(status["state"] == "success")
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get CI status", error=str(e))
        return None

    def _get_oldest_age_hours(self, items: list[dict[str, Any]]) -> float:
        """Get age in hours of the oldest item."""
        now = datetime.now(UTC)
        oldest = min(datetime.fromisoformat(i["created_at"].replace("Z", "+00:00")) for i in items)
        return (now - oldest).total_seconds() / 3600

    def _get_oldest_age_days(self, items: list[dict[str, Any]]) -> float:
        """Get age in days of the oldest item."""
        return self._get_oldest_age_hours(items) / 24

    async def _get_release_count_30d(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> int:
        """Get the number of releases published in the last 30 days (capped at 10)."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/releases",
                headers=self._get_headers(),
                params={"per_page": 100},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            releases: list[dict[str, Any]] = resp.json()
            cutoff = datetime.now(UTC) - timedelta(days=30)
            count = sum(
                1
                for r in releases
                if r.get("published_at")
                and datetime.fromisoformat(
                    r["published_at"].replace("Z", "+00:00")
                ) >= cutoff
            )
            return min(count, 10)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get releases", error=str(e))
        return 0

    async def _get_contributor_count_90d(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> int:
        """Get the number of unique commit authors in the last 90 days (capped at 20)."""
        try:
            since = (datetime.now(UTC) - timedelta(days=90)).isoformat()
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"since": since, "per_page": 100},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            authors = {
                c["author"]["login"]
                for c in commits
                if c.get("author") and c["author"].get("login")
            }
            return min(len(authors), 20)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get contributor count", error=str(e))
        return 0

    async def list_user_repos(
        self, page: int = 1, per_page: int = 100
    ) -> list[dict[str, Any]]:
        """List repositories accessible to the authenticated user."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/user/repos",
                    headers=self._get_headers(),
                    params={
                        "per_page": per_page,
                        "page": page,
                        "sort": "pushed",
                        "affiliation": "owner,collaborator,organization_member",
                    },
                )
                self._check_rate_limit(resp)
                resp.raise_for_status()
                result: list[dict[str, Any]] = resp.json()
                return result
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning("Failed to list user repos", error=str(e))
                return []
