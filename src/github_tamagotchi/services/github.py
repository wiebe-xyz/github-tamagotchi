"""GitHub API service for repository health metrics."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from github_tamagotchi import metrics as metrics_service
from github_tamagotchi.core.config import settings
from github_tamagotchi.core.telemetry import get_tracer

logger = structlog.get_logger()
_tracer = get_tracer(__name__)


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
    security_alerts_critical: int = 0
    security_alerts_high: int = 0
    security_alerts_medium: int = 0
    security_alerts_low: int = 0
    dependent_count: int = 0
    star_count: int = 0
    fork_count: int = 0


@dataclass
class WeeklyCommits:
    """Commits for a single week."""

    week_label: str  # e.g. "Mar 10"
    count: int


@dataclass
class RepoInsights:
    """Detailed insights metrics for a GitHub repository."""

    # Commit frequency over last 30 days, broken into 4 weekly buckets
    weekly_commits: list[WeeklyCommits]
    total_commits_30d: int

    # PR lifecycle
    avg_pr_merge_hours: float | None  # None if no merged PRs found
    open_prs_count: int

    # Issue response time
    avg_issue_response_hours: float | None  # None if no issues with responses

    # CI health
    ci_pass_rate: float | None  # 0.0–1.0, None if no CI data
    ci_runs_checked: int

    # Contributor activity
    contributor_count_90d: int


@dataclass
class ContributorStats:
    """Activity stats for a single contributor to a repository."""

    commits_30d: int
    last_commit_at: datetime | None
    is_top_contributor: bool  # has most commits among all contributors in last 30d
    has_failed_ci: bool  # latest commit has failing CI checks
    days_since_last_commit: int | None  # None if no commits ever found


@dataclass
class AllContributorActivity:
    """Activity for all contributors in a repository over the last 30 days."""

    # Maps github_username -> commit count in last 30d
    commits_by_user: dict[str, int]
    # Maps github_username -> merged PR count in last 30d
    merged_prs_by_user: dict[str, int]
    # Maps github_username -> last activity datetime
    last_activity_by_user: dict[str, datetime]


@dataclass
class BlameEntry:
    """A single blame entry showing who is responsible for a pet health issue."""

    issue: str  # human-readable description of the problem
    culprit: str  # GitHub username
    how_long: str  # human-readable duration (e.g. "2 days", "4 hours")


@dataclass
class HeroEntry:
    """A single hero entry showing who contributed positively to pet health."""

    good_deed: str  # human-readable description of the good deed
    hero: str  # GitHub username
    when: str  # human-readable time (e.g. "Today", "This week")


@dataclass
class BlameBoardData:
    """Aggregated blame/hero board data for a repository."""

    is_healthy: bool
    blame_entries: list[BlameEntry]
    hero_entries: list[HeroEntry]


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
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            metrics_service.github_api_rate_limit_remaining.set(int(remaining))

        # Extract the resource type from the URL path (e.g. "commits", "pulls") for labelling.
        # response.url requires a request to be set; fall back to "unknown" in test scenarios.
        endpoint_label = "unknown"
        try:
            url_path = str(response.url.path)
            path_parts = [p for p in url_path.split("/") if p]
            if path_parts:
                endpoint_label = path_parts[-1]
        except RuntimeError:
            pass
        metrics_service.github_api_requests_total.labels(
            endpoint=endpoint_label,
            status=str(response.status_code),
        ).inc()

        if response.status_code == 403 and remaining is not None and int(remaining) == 0:
            metrics_service.github_api_errors_total.labels(error_type="rate_limited").inc()
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
        with _tracer.start_as_current_span(
            "github.get_repo_health",
            attributes={"github.repo": f"{owner}/{repo}"},
        ):
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

                # Get security alerts
                security_counts = await self._get_security_alerts(client, owner, repo)

                # Get dependent count (repos/packages that depend on this one)
                dependent_count = await self._get_dependent_count(client, owner, repo)

                # Get star and fork counts
                star_count, fork_count = await self._get_star_fork_counts(client, owner, repo)

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
                    security_alerts_critical=security_counts["critical"],
                    security_alerts_high=security_counts["high"],
                    security_alerts_medium=security_counts["medium"],
                    security_alerts_low=security_counts["low"],
                    dependent_count=dependent_count,
                    star_count=star_count,
                    fork_count=fork_count,
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
                dt = datetime.fromisoformat(
                    commits[0]["commit"]["committer"]["date"].replace("Z", "+00:00")
                )
                # Ensure the datetime is always timezone-aware (defensive guard
                # against any API response that omits a timezone offset).
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
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

    async def _get_security_alerts(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> dict[str, int]:
        """Get open Dependabot security alert counts by severity."""
        counts: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/dependabot/alerts",
                headers=self._get_headers(),
                params={"state": "open", "per_page": 100},
            )
            self._check_rate_limit(resp)
            if resp.status_code == 404:
                # Dependabot not enabled or no access — treat as no alerts
                return counts
            resp.raise_for_status()
            alerts: list[dict[str, Any]] = resp.json()
            for alert in alerts:
                severity = alert.get("security_advisory", {}).get("severity", "").lower()
                if severity in counts:
                    counts[severity] += 1
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get security alerts", error=str(e))
        return counts

    async def _get_star_fork_counts(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> tuple[int, int]:
        """Get the star and fork counts for the repository."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}",
                headers=self._get_headers(),
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data.get("stargazers_count", 0), data.get("forks_count", 0)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get star/fork counts", error=str(e))
        return 0, 0

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

    async def _get_dependent_count(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> int:
        """Get the number of repositories that depend on this repo.

        Scrapes the GitHub network/dependents page since there is no REST API.
        Returns 0 on any error or when the page is unavailable.
        """
        try:
            resp = await client.get(
                f"https://github.com/{owner}/{repo}/network/dependents",
                headers={"Accept": "text/html"},
                follow_redirects=True,
                timeout=10,
            )
            if resp.status_code != 200:
                return 0
            # Parse "N Repositories" or "N,NNN Repositories" from the page
            match = re.search(r"([\d,]+)\s+Repositor", resp.text)
            if match:
                return int(match.group(1).replace(",", ""))
        except Exception as e:
            logger.warning("Failed to get dependent count", error=str(e))
        return 0

    async def get_contributor_stats(self, owner: str, repo: str, username: str) -> ContributorStats:
        """Fetch activity stats for a specific contributor in a repository."""
        with _tracer.start_as_current_span(
            "github.get_contributor_stats",
            attributes={"github.repo": f"{owner}/{repo}", "github.username": username},
        ):
            async with httpx.AsyncClient() as client:
                since_30d = (datetime.now(UTC) - timedelta(days=30)).isoformat()

                # Get user's commits in last 30d and all commits in last 30d (for top-contributor check)
                user_commits, all_commits = await self._fetch_commits_parallel(
                    client, owner, repo, username, since_30d
                )

                commits_30d = len(user_commits)

                # Determine last commit date (from user commits, or fall back to all-time lookup)
                last_commit_at: datetime | None = None
                if user_commits:
                    raw_date = (
                        user_commits[0]
                        .get("commit", {})
                        .get("committer", {})
                        .get("date")
                    )
                    if raw_date:
                        last_commit_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                elif commits_30d == 0:
                    # Try 90d window to detect absence vs. complete stranger
                    last_commit_at = await self._get_user_last_commit(client, owner, repo, username)

                # Determine if this user is the top contributor in last 30d
                is_top_contributor = False
                if commits_30d > 0 and all_commits:
                    author_counts: dict[str, int] = {}
                    for c in all_commits:
                        login = (
                            c["author"].get("login") if c.get("author") else None
                        )
                        if login:
                            author_counts[login] = author_counts.get(login, 0) + 1
                    top_count = max(author_counts.values(), default=0)
                    user_count = author_counts.get(username, 0)
                    is_top_contributor = user_count >= 3 and user_count == top_count

                # Check CI status of user's latest commit
                has_failed_ci = False
                if user_commits:
                    latest_sha = user_commits[0].get("sha", "")
                    if latest_sha:
                        has_failed_ci = await self._has_failed_ci(client, owner, repo, latest_sha)

                days_since: int | None = None
                if last_commit_at:
                    days_since = max(0, (datetime.now(UTC) - last_commit_at).days)

                return ContributorStats(
                    commits_30d=commits_30d,
                    last_commit_at=last_commit_at,
                    is_top_contributor=is_top_contributor,
                    has_failed_ci=has_failed_ci,
                    days_since_last_commit=days_since,
                )

    async def _fetch_commits_parallel(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        username: str,
        since: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch user-specific and all commits concurrently."""
        import asyncio

        async def _fetch(params: dict[str, Any]) -> list[dict[str, Any]]:
            try:
                resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/commits",
                    headers=self._get_headers(),
                    params=params,
                )
                self._check_rate_limit(resp)
                resp.raise_for_status()
                result: list[dict[str, Any]] = resp.json()
                return result
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning("Failed to fetch commits", error=str(e))
                return []

        user_task = _fetch({"author": username, "since": since, "per_page": 100})
        all_task = _fetch({"since": since, "per_page": 100})
        return await asyncio.gather(user_task, all_task)

    async def _get_user_last_commit(
        self, client: httpx.AsyncClient, owner: str, repo: str, username: str
    ) -> datetime | None:
        """Get the date of a user's last commit regardless of time window."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"author": username, "per_page": 1},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            if commits:
                raw_date = (
                    commits[0].get("commit", {}).get("committer", {}).get("date")
                )
                if raw_date:
                    return datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get user last commit", error=str(e))
        return None

    async def _has_failed_ci(
        self, client: httpx.AsyncClient, owner: str, repo: str, sha: str
    ) -> bool:
        """Return True if the given commit has any failing CI check runs."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits/{sha}/check-runs",
                headers=self._get_headers(),
                params={"per_page": 30},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            runs: list[dict[str, Any]] = data.get("check_runs", [])
            return any(
                r.get("conclusion") in ("failure", "timed_out", "action_required")
                for r in runs
            )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get check runs", sha=sha, error=str(e))
        return False

    async def get_all_contributor_activity(
        self, owner: str, repo: str
    ) -> AllContributorActivity:
        """Fetch commit and PR activity for all contributors in the last 30 days."""
        with _tracer.start_as_current_span(
            "github.get_contributor_activity",
            attributes={"github.repo": f"{owner}/{repo}"},
        ):
            async with httpx.AsyncClient() as client:
                since_30d = (datetime.now(UTC) - timedelta(days=30)).isoformat()

                commits_by_user: dict[str, int] = {}
                last_activity_by_user: dict[str, datetime] = {}

                try:
                    resp = await client.get(
                        f"{self.base_url}/repos/{owner}/{repo}/commits",
                        headers=self._get_headers(),
                        params={"since": since_30d, "per_page": 100},
                    )
                    self._check_rate_limit(resp)
                    resp.raise_for_status()
                    commits: list[dict[str, Any]] = resp.json()
                    for commit in commits:
                        login = (
                            commit["author"].get("login") if commit.get("author") else None
                        )
                        if not login:
                            continue
                        commits_by_user[login] = commits_by_user.get(login, 0) + 1
                        raw_date = commit.get("commit", {}).get("committer", {}).get("date")
                        if raw_date:
                            commit_dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                            existing = last_activity_by_user.get(login)
                            if existing is None or commit_dt > existing:
                                last_activity_by_user[login] = commit_dt
                except RateLimitError:
                    raise
                except Exception as e:
                    logger.warning("Failed to fetch all contributor commits", error=str(e))

                merged_prs_by_user: dict[str, int] = {}

                try:
                    resp = await client.get(
                        f"{self.base_url}/repos/{owner}/{repo}/pulls",
                        headers=self._get_headers(),
                        params={"state": "closed", "per_page": 100},
                    )
                    self._check_rate_limit(resp)
                    resp.raise_for_status()
                    prs: list[dict[str, Any]] = resp.json()
                    cutoff = datetime.now(UTC) - timedelta(days=30)
                    for pr in prs:
                        merged_at_raw = pr.get("merged_at")
                        if not merged_at_raw:
                            continue
                        merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
                        if merged_at < cutoff:
                            continue
                        merged_by = pr.get("merged_by") or {}
                        login = merged_by.get("login")
                        if not login:
                            continue
                        merged_prs_by_user[login] = merged_prs_by_user.get(login, 0) + 1
                        existing = last_activity_by_user.get(login)
                        if existing is None or merged_at > existing:
                            last_activity_by_user[login] = merged_at
                except RateLimitError:
                    raise
                except Exception as e:
                    logger.warning(
                        "Failed to fetch merged PRs for contributor activity", error=str(e)
                    )

                return AllContributorActivity(
                    commits_by_user=commits_by_user,
                    merged_prs_by_user=merged_prs_by_user,
                    last_activity_by_user=last_activity_by_user,
                )

    async def get_repo_insights(self, owner: str, repo: str) -> RepoInsights:
        """Fetch detailed insights metrics for a repository."""
        with _tracer.start_as_current_span(
            "github.get_repo_insights",
            attributes={"github.repo": f"{owner}/{repo}"},
        ):
            async with httpx.AsyncClient() as client:
                weekly_commits, total_commits = await self._get_weekly_commits_30d(client, owner, repo)
                avg_merge_hours = await self._get_avg_pr_merge_hours(client, owner, repo)
                open_prs = await self._get_open_prs(client, owner, repo)
                avg_response_hours = await self._get_avg_issue_response_hours(client, owner, repo)
                ci_pass_rate, ci_runs = await self._get_ci_pass_rate(client, owner, repo)
                contributors = await self._get_contributor_count_90d(client, owner, repo)

            return RepoInsights(
                weekly_commits=weekly_commits,
                total_commits_30d=total_commits,
                avg_pr_merge_hours=avg_merge_hours,
                open_prs_count=len(open_prs),
                avg_issue_response_hours=avg_response_hours,
                ci_pass_rate=ci_pass_rate,
                ci_runs_checked=ci_runs,
                contributor_count_90d=contributors,
            )

    async def _get_weekly_commits_30d(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> tuple[list[WeeklyCommits], int]:
        """Get commits grouped by week for the last 28 days (4 weekly buckets)."""
        now = datetime.now(UTC)
        since = now - timedelta(days=28)
        buckets: list[WeeklyCommits] = []
        total = 0
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"since": since.isoformat(), "per_page": 100},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            total = len(commits)
            for week_idx in range(4):
                week_start = since + timedelta(weeks=week_idx)
                week_end = week_start + timedelta(weeks=1)
                count = sum(
                    1
                    for c in commits
                    if c.get("commit", {}).get("committer", {}).get("date")
                    and week_start
                    <= datetime.fromisoformat(
                        c["commit"]["committer"]["date"].replace("Z", "+00:00")
                    )
                    < week_end
                )
                buckets.append(WeeklyCommits(week_label=week_start.strftime("%b %-d"), count=count))
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get weekly commits", error=str(e))
            for week_idx in range(4):
                week_start = since + timedelta(weeks=week_idx)
                buckets.append(WeeklyCommits(week_label=week_start.strftime("%b %-d"), count=0))
        return buckets, total

    async def _get_avg_pr_merge_hours(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> float | None:
        """Get average time in hours from PR open to merge for recently closed PRs."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/pulls",
                headers=self._get_headers(),
                params={"state": "closed", "per_page": 20, "sort": "updated", "direction": "desc"},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            prs: list[dict[str, Any]] = resp.json()
            durations = []
            for pr in prs:
                if pr.get("merged_at") and pr.get("created_at"):
                    created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
                    merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
                    durations.append((merged - created).total_seconds() / 3600)
            if not durations:
                return None
            return sum(durations) / len(durations)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get PR merge times", error=str(e))
        return None

    async def _get_avg_issue_response_hours(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> float | None:
        """Get average time in hours from issue creation to first comment."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/issues",
                headers=self._get_headers(),
                params={"state": "all", "per_page": 20, "sort": "updated", "direction": "desc"},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            issues: list[dict[str, Any]] = resp.json()
            issues = [i for i in issues if "pull_request" not in i and i.get("comments", 0) > 0]
            if not issues:
                return None
            response_times = []
            for issue in issues[:10]:
                comments_resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/issues/{issue['number']}/comments",
                    headers=self._get_headers(),
                    params={"per_page": 1},
                )
                self._check_rate_limit(comments_resp)
                if comments_resp.status_code != 200:
                    continue
                comments: list[dict[str, Any]] = comments_resp.json()
                if not comments:
                    continue
                created = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
                first_response = datetime.fromisoformat(
                    comments[0]["created_at"].replace("Z", "+00:00")
                )
                response_times.append((first_response - created).total_seconds() / 3600)
            if not response_times:
                return None
            return sum(response_times) / len(response_times)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get issue response times", error=str(e))
        return None

    async def _get_ci_pass_rate(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> tuple[float | None, int]:
        """Get CI pass rate from recent check runs on the default branch."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}",
                headers=self._get_headers(),
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            repo_data: dict[str, Any] = resp.json()
            default_branch: str = repo_data["default_branch"]

            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"sha": default_branch, "per_page": 10},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            if not commits:
                return None, 0

            statuses: list[bool] = []
            for commit in commits:
                sha = commit["sha"]
                check_resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/commits/{sha}/check-runs",
                    headers={**self._get_headers(), "Accept": "application/vnd.github+json"},
                    params={"per_page": 1},
                )
                if check_resp.status_code != 200:
                    continue
                data: dict[str, Any] = check_resp.json()
                runs: list[dict[str, Any]] = data.get("check_runs", [])
                if not runs:
                    continue
                conclusion = runs[0].get("conclusion")
                if conclusion in ("success", "failure", "timed_out", "cancelled"):
                    statuses.append(conclusion == "success")

            if not statuses:
                return None, 0
            return sum(statuses) / len(statuses), len(statuses)
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get CI pass rate", error=str(e))
        return None, 0

    async def get_blame_board_data(
        self, owner: str, repo: str, pet_health: int, pet_mood: str
    ) -> BlameBoardData:
        """Fetch blame/hero board data for a repository.

        When the pet is unhealthy (health < 50 or mood is negative), returns blame
        entries showing who is responsible. When healthy, returns hero entries showing
        who deserves credit.
        """
        with _tracer.start_as_current_span(
            "github.get_blame_board",
            attributes={"github.repo": f"{owner}/{repo}"},
        ):
            unhealthy_moods = {"sick", "hungry", "worried", "lonely"}
            is_healthy = pet_health >= 50 and pet_mood not in unhealthy_moods

            async with httpx.AsyncClient() as client:
                if is_healthy:
                    hero_entries = await self._build_hero_entries(client, owner, repo)
                    return BlameBoardData(
                        is_healthy=True,
                        blame_entries=[],
                        hero_entries=hero_entries,
                    )
                else:
                    blame_entries = await self._build_blame_entries(
                        client, owner, repo, pet_mood
                    )
                    return BlameBoardData(
                        is_healthy=False,
                        blame_entries=blame_entries,
                        hero_entries=[],
                    )

    def _format_duration(self, dt: datetime) -> str:
        """Format a datetime as a human-readable 'how long ago' string."""
        now = datetime.now(UTC)
        delta = now - dt
        total_hours = delta.total_seconds() / 3600
        if total_hours < 2:
            return "just now"
        if total_hours < 24:
            return f"{int(total_hours)} hours"
        days = int(total_hours / 24)
        if days == 1:
            return "1 day"
        return f"{days} days"

    def _format_when(self, dt: datetime) -> str:
        """Format a datetime as a human-readable 'when' string."""
        now = datetime.now(UTC)
        delta = now - dt
        total_hours = delta.total_seconds() / 3600
        if total_hours < 24:
            return "Today"
        if total_hours < 48:
            return "Yesterday"
        days = int(total_hours / 24)
        if days <= 7:
            return "This week"
        return f"{days} days ago"

    async def _build_blame_entries(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        pet_mood: str,
    ) -> list[BlameEntry]:
        """Build blame entries for an unhealthy pet."""
        entries: list[BlameEntry] = []

        # Broken CI: find the author of the last failing commit on the default branch
        ci_blame = await self._get_ci_blame(client, owner, repo)
        if ci_blame:
            entries.append(ci_blame)

        # Stale PRs: find reviewers on long-open PRs
        pr_blames = await self._get_stale_pr_blames(client, owner, repo)
        entries.extend(pr_blames)

        # No recent commits: show last committer
        if pet_mood == "hungry" and not entries:
            commit_blame = await self._get_last_committer_blame(client, owner, repo)
            if commit_blame:
                entries.append(commit_blame)

        return entries[:5]  # cap at 5 entries

    async def _get_ci_blame(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> BlameEntry | None:
        """Return a blame entry if CI is currently broken."""
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

            # Get latest commit on default branch
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"sha": default_branch, "per_page": 1},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            if not commits:
                return None

            latest_commit = commits[0]
            sha = latest_commit["sha"]
            author_login: str | None = (
                latest_commit["author"]["login"] if latest_commit.get("author") else None
            )
            commit_date_raw: str | None = (
                latest_commit.get("commit", {}).get("committer", {}).get("date")
            )

            # Check CI status for this commit
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits/{sha}/check-runs",
                headers={**self._get_headers(), "Accept": "application/vnd.github+json"},
                params={"per_page": 30},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            runs: list[dict[str, Any]] = data.get("check_runs", [])

            has_failure = any(
                r.get("conclusion") in ("failure", "timed_out", "action_required")
                for r in runs
                if r.get("status") == "completed"
            )
            all_success = runs and all(
                r.get("conclusion") == "success"
                for r in runs
                if r.get("status") == "completed"
            )

            if not has_failure or all_success:
                return None

            if not author_login:
                return None

            how_long = "unknown"
            if commit_date_raw:
                commit_dt = datetime.fromisoformat(commit_date_raw.replace("Z", "+00:00"))
                how_long = self._format_duration(commit_dt)

            return BlameEntry(
                issue="CI broken",
                culprit=author_login,
                how_long=how_long,
            )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get CI blame", error=str(e))
        return None

    async def _get_stale_pr_blames(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> list[BlameEntry]:
        """Return blame entries for PRs with requested reviewers that are long overdue."""
        entries: list[BlameEntry] = []
        try:
            prs = await self._get_open_prs(client, owner, repo)
            now = datetime.now(UTC)
            for pr in prs:
                created_at_raw: str | None = pr.get("created_at")
                if not created_at_raw:
                    continue
                created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
                age_hours = (now - created_at).total_seconds() / 3600
                if age_hours < 48:
                    continue

                # Get requested reviewers
                reviewers: list[dict[str, Any]] = pr.get("requested_reviewers", [])
                pr_title: str = pr.get("title", f"PR #{pr.get('number', '?')}")
                pr_number: int = pr.get("number", 0)
                display_title = f"PR #{pr_number} needs review"
                if len(pr_title) <= 40:
                    display_title = f'"{pr_title}" needs review'

                how_long = self._format_duration(created_at)
                if reviewers:
                    for reviewer in reviewers[:2]:  # at most 2 reviewers per PR
                        login: str | None = reviewer.get("login")
                        if login:
                            entries.append(
                                BlameEntry(
                                    issue=display_title,
                                    culprit=login,
                                    how_long=how_long,
                                )
                            )
                else:
                    # No reviewer assigned — blame the PR author
                    pr_user: dict[str, Any] | None = pr.get("user")
                    author_login: str | None = pr_user.get("login") if pr_user else None
                    if author_login:
                        entries.append(
                            BlameEntry(
                                issue=display_title,
                                culprit=author_login,
                                how_long=how_long,
                            )
                        )
                if len(entries) >= 3:
                    break
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get stale PR blames", error=str(e))
        return entries

    async def _get_last_committer_blame(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> BlameEntry | None:
        """Return a blame entry for the last committer when repo has gone quiet."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"per_page": 1},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            if not commits:
                return None

            commit = commits[0]
            author_login: str | None = (
                commit["author"]["login"] if commit.get("author") else None
            )
            commit_date_raw: str | None = (
                commit.get("commit", {}).get("committer", {}).get("date")
            )
            if not author_login or not commit_date_raw:
                return None

            commit_dt = datetime.fromisoformat(commit_date_raw.replace("Z", "+00:00"))
            how_long = self._format_duration(commit_dt)
            return BlameEntry(
                issue="No recent commits",
                culprit=author_login,
                how_long=f"last commit {how_long} ago",
            )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get last committer", error=str(e))
        return None

    async def _build_hero_entries(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> list[HeroEntry]:
        """Build hero entries for a healthy pet."""
        entries: list[HeroEntry] = []

        # Top committer in last 30d
        top_committer = await self._get_top_committer_hero(client, owner, repo)
        if top_committer:
            entries.append(top_committer)

        # Recent PR mergers
        pr_heroes = await self._get_pr_merger_heroes(client, owner, repo)
        entries.extend(pr_heroes)

        # CI passing — author of latest commit
        ci_hero = await self._get_ci_fixer_hero(client, owner, repo)
        if ci_hero:
            entries.append(ci_hero)

        # Deduplicate by hero+deed pair while preserving order
        seen: set[tuple[str, str]] = set()
        unique: list[HeroEntry] = []
        for e in entries:
            key = (e.hero, e.good_deed)
            if key not in seen:
                seen.add(key)
                unique.append(e)

        return unique[:5]  # cap at 5 entries

    async def _get_top_committer_hero(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> HeroEntry | None:
        """Return a hero entry for the top committer in the last 30 days."""
        try:
            since = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"since": since, "per_page": 100},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            if not commits:
                return None

            counts: dict[str, int] = {}
            for c in commits:
                login = c["author"]["login"] if c.get("author") else None
                if login:
                    counts[login] = counts.get(login, 0) + 1

            if not counts:
                return None

            top_login = max(counts, key=lambda k: counts[k])
            top_count = counts[top_login]
            if top_count < 2:
                return None

            return HeroEntry(
                good_deed=f"Merged {top_count} commit{'s' if top_count != 1 else ''} (30d)",
                hero=top_login,
                when="This month",
            )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get top committer hero", error=str(e))
        return None

    async def _get_pr_merger_heroes(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> list[HeroEntry]:
        """Return hero entries for contributors who merged PRs recently."""
        entries: list[HeroEntry] = []
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/pulls",
                headers=self._get_headers(),
                params={
                    "state": "closed",
                    "per_page": 20,
                    "sort": "updated",
                    "direction": "desc",
                },
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            prs: list[dict[str, Any]] = resp.json()

            merger_counts: dict[str, int] = {}
            merger_latest: dict[str, datetime] = {}
            cutoff = datetime.now(UTC) - timedelta(days=30)

            for pr in prs:
                merged_at_raw: str | None = pr.get("merged_at")
                merged_by: dict[str, Any] | None = pr.get("merged_by")
                if not merged_at_raw or not merged_by:
                    continue
                merged_at = datetime.fromisoformat(merged_at_raw.replace("Z", "+00:00"))
                if merged_at < cutoff:
                    continue
                login: str | None = merged_by.get("login")
                if not login:
                    continue
                merger_counts[login] = merger_counts.get(login, 0) + 1
                if login not in merger_latest or merged_at > merger_latest[login]:
                    merger_latest[login] = merged_at

            # Return top 2 mergers
            sorted_mergers = sorted(merger_counts, key=lambda k: merger_counts[k], reverse=True)
            for login in sorted_mergers[:2]:
                count = merger_counts[login]
                when = self._format_when(merger_latest[login])
                entries.append(
                    HeroEntry(
                        good_deed=f"Merged {count} PR{'s' if count != 1 else ''}",
                        hero=login,
                        when=when,
                    )
                )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get PR merger heroes", error=str(e))
        return entries

    async def _get_ci_fixer_hero(
        self, client: httpx.AsyncClient, owner: str, repo: str
    ) -> HeroEntry | None:
        """Return a hero entry for the author of the latest successful commit with passing CI."""
        try:
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}",
                headers=self._get_headers(),
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            repo_data: dict[str, Any] = resp.json()
            default_branch: str = repo_data["default_branch"]

            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits",
                headers=self._get_headers(),
                params={"sha": default_branch, "per_page": 1},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            commits: list[dict[str, Any]] = resp.json()
            if not commits:
                return None

            commit = commits[0]
            sha = commit["sha"]
            author_login: str | None = (
                commit["author"]["login"] if commit.get("author") else None
            )
            commit_date_raw: str | None = (
                commit.get("commit", {}).get("committer", {}).get("date")
            )

            if not author_login:
                return None

            # Check if CI is passing for this commit
            resp = await client.get(
                f"{self.base_url}/repos/{owner}/{repo}/commits/{sha}/check-runs",
                headers={**self._get_headers(), "Accept": "application/vnd.github+json"},
                params={"per_page": 30},
            )
            self._check_rate_limit(resp)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            runs: list[dict[str, Any]] = data.get("check_runs", [])

            completed_runs = [r for r in runs if r.get("status") == "completed"]
            if not completed_runs:
                return None

            all_pass = all(r.get("conclusion") == "success" for r in completed_runs)
            if not all_pass:
                return None

            when = "Today"
            if commit_date_raw:
                commit_dt = datetime.fromisoformat(commit_date_raw.replace("Z", "+00:00"))
                when = self._format_when(commit_dt)

            return HeroEntry(
                good_deed="CI passing",
                hero=author_login,
                when=when,
            )
        except RateLimitError:
            raise
        except Exception as e:
            logger.warning("Failed to get CI fixer hero", error=str(e))
        return None

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

    async def get_top_contributor(self, owner: str, repo: str) -> str | None:
        """Return the GitHub login of the top committer in the last 30 days, or None."""
        async with httpx.AsyncClient() as client:
            since_30d = (datetime.now(UTC) - timedelta(days=30)).isoformat()
            try:
                resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/commits",
                    headers=self._get_headers(),
                    params={"since": since_30d, "per_page": 100},
                )
                self._check_rate_limit(resp)
                resp.raise_for_status()
                commits: list[dict[str, Any]] = resp.json()
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning(
                    "Failed to get top contributor", repo=f"{owner}/{repo}", error=str(e)
                )
                return None

        author_counts: dict[str, int] = {}
        for c in commits:
            login = c["author"].get("login") if c.get("author") else None
            if login:
                author_counts[login] = author_counts.get(login, 0) + 1

        if not author_counts:
            return None
        return max(author_counts, key=lambda k: author_counts[k])

    async def get_repo_permission(self, owner: str, repo: str, username: str) -> str | None:
        """Get the permission level of a user on a repo.

        Returns one of: "admin", "write", "read", "none", or None on error.
        Uses the authenticated user's token (self.token) to call the API.
        """
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/repos/{owner}/{repo}/collaborators/{username}/permission",
                    headers=self._get_headers(),
                )
                self._check_rate_limit(resp)
                if resp.status_code == 404:
                    return "none"
                resp.raise_for_status()
                data = resp.json()
                permission: str = data.get("permission", "none")
                return permission
            except RateLimitError:
                raise
            except Exception as e:
                logger.warning("Failed to get repo permission", error=str(e))
                return None
