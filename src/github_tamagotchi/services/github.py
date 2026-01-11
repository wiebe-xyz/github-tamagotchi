"""GitHub API service for repository health metrics."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from github_tamagotchi.core.config import settings

logger = structlog.get_logger()


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

            return RepoHealth(
                last_commit_at=last_commit_at,
                open_prs_count=open_prs_count,
                oldest_pr_age_hours=oldest_pr_age,
                open_issues_count=open_issues_count,
                oldest_issue_age_days=oldest_issue_age,
                last_ci_success=last_ci_success,
                has_stale_dependencies=False,  # TODO: Check dependabot
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
            resp.raise_for_status()
            commits = resp.json()
            if commits:
                return datetime.fromisoformat(
                    commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00")
                )
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
            resp.raise_for_status()
            result: list[dict[str, Any]] = resp.json()
            return result
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
            resp.raise_for_status()
            # Filter out PRs (they appear in issues endpoint too)
            data: list[dict[str, Any]] = resp.json()
            return [i for i in data if "pull_request" not in i]
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
            resp.raise_for_status()
            repo_data: dict[str, Any] = resp.json()
            default_branch: str = repo_data["default_branch"]

            # Get combined status
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits/{default_branch}/status",
                headers=self._get_headers(),
            )
            resp.raise_for_status()
            status: dict[str, Any] = resp.json()
            return bool(status["state"] == "success")
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
