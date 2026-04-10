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

    async def get_contributor_stats(self, owner: str, repo: str, username: str) -> ContributorStats:
        """Fetch activity stats for a specific contributor in a repository."""
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

    async def get_repo_insights(self, owner: str, repo: str) -> RepoInsights:
        """Fetch detailed insights metrics for a repository."""
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

    async def get_contributor_stats(self, owner: str, repo: str, username: str) -> ContributorStats:
        """Fetch activity stats for a specific contributor in a repository."""
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
                    login = c["author"].get("login") if c.get("author") else None
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
                raw_date = commits[0].get("commit", {}).get("committer", {}).get("date")
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
