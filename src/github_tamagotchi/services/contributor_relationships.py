"""Service for managing pet-contributor relationship scores and standings."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from github_tamagotchi.models.contributor_relationship import ContributorStanding
from github_tamagotchi.services.github import AllContributorActivity


@dataclass
class ContributorUpdate:
    """Computed update data for a single contributor."""

    github_username: str
    score: int
    standing: str
    last_activity: datetime | None
    good_deeds: list[str] = field(default_factory=list)
    sins: list[str] = field(default_factory=list)


# Score weights (matching issue specification)
SCORE_PER_COMMIT = 5
SCORE_PER_MERGED_PR = 10

# Standing thresholds
GOOD_SCORE_THRESHOLD = 50
ABSENT_DAYS_THRESHOLD = 30

# Maximum recent events to keep in sins/good_deeds lists
MAX_RECENT_EVENTS = 5


def calculate_score(commits_30d: int, merged_prs_30d: int) -> int:
    """Calculate contributor score from 30-day activity."""
    return commits_30d * SCORE_PER_COMMIT + merged_prs_30d * SCORE_PER_MERGED_PR


def calculate_standing(
    score: int,
    is_top_scorer: bool,
    last_activity: datetime | None,
    now: datetime,
) -> str:
    """Determine standing from score and activity.

    Returns one of: favorite, good, neutral, doghouse, absent.
    """
    if last_activity is None:
        return ContributorStanding.ABSENT

    days_inactive = (now - last_activity).total_seconds() / 86400
    if days_inactive >= ABSENT_DAYS_THRESHOLD:
        return ContributorStanding.ABSENT

    if score < 0:
        return ContributorStanding.DOGHOUSE

    if is_top_scorer:
        return ContributorStanding.FAVORITE

    if score > GOOD_SCORE_THRESHOLD:
        return ContributorStanding.GOOD

    return ContributorStanding.NEUTRAL


def build_contributor_updates(
    activity: AllContributorActivity,
    now: datetime | None = None,
) -> list[ContributorUpdate]:
    """Compute score, standing, and event lists for each contributor."""
    if now is None:
        now = datetime.now(UTC)

    all_usernames = set(activity.commits_by_user) | set(activity.merged_prs_by_user)

    # Find top scorer for "favorite" standing
    scores: dict[str, int] = {
        username: calculate_score(
            activity.commits_by_user.get(username, 0),
            activity.merged_prs_by_user.get(username, 0),
        )
        for username in all_usernames
    }
    max_score = max(scores.values(), default=0)

    updates: list[ContributorUpdate] = []
    for username in all_usernames:
        commits = activity.commits_by_user.get(username, 0)
        merged_prs = activity.merged_prs_by_user.get(username, 0)
        score = scores[username]
        last_activity = activity.last_activity_by_user.get(username)
        is_top = score > 0 and score == max_score

        standing = calculate_standing(score, is_top, last_activity, now)

        good_deeds: list[str] = []
        if commits > 0:
            good_deeds.append(f"{commits} commit{'s' if commits != 1 else ''} in last 30 days")
        if merged_prs > 0:
            pr_label = f"PR{'s' if merged_prs != 1 else ''}"
            good_deeds.append(f"{merged_prs} {pr_label} merged in last 30 days")
        good_deeds = good_deeds[:MAX_RECENT_EVENTS]

        updates.append(
            ContributorUpdate(
                github_username=username,
                score=score,
                standing=standing,
                last_activity=last_activity,
                good_deeds=good_deeds,
                sins=[],
            )
        )

    return updates
