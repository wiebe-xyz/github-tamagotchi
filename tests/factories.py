"""Test data factories for creating test objects with sensible defaults."""

from datetime import UTC, datetime, timedelta

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import RepoHealth


def make_pet(
    *,
    repo_owner: str = "testuser",
    repo_name: str = "testrepo",
    name: str = "TestPet",
    stage: str = PetStage.EGG.value,
    mood: str = PetMood.CONTENT.value,
    health: int = 100,
    experience: int = 0,
    last_fed_at: datetime | None = None,
    last_checked_at: datetime | None = None,
    commit_streak: int = 0,
    longest_streak: int = 0,
    last_streak_date: datetime | None = None,
    created_at: datetime | None = None,
    is_dead: bool = False,
    died_at: datetime | None = None,
    cause_of_death: str | None = None,
    grace_period_started: datetime | None = None,
    generation: int = 1,
) -> Pet:
    """Create a Pet instance with sensible defaults."""
    pet = Pet(
        repo_owner=repo_owner,
        repo_name=repo_name,
        name=name,
        stage=stage,
        mood=mood,
        health=health,
        experience=experience,
        last_fed_at=last_fed_at,
        last_checked_at=last_checked_at,
        commit_streak=commit_streak,
        longest_streak=longest_streak,
        last_streak_date=last_streak_date,
        is_dead=is_dead,
        died_at=died_at,
        cause_of_death=cause_of_death,
        grace_period_started=grace_period_started,
        generation=generation,
    )
    # created_at has a server_default but isn't set by __init__; set it explicitly
    # so unit tests that don't hit the DB have a non-None value
    pet.created_at = (
        created_at if created_at is not None else datetime.now(UTC) - timedelta(days=90)
    )
    return pet


def make_repo_health(
    *,
    last_commit_at: datetime | None = None,
    commit_hours_ago: float | None = 1.0,
    open_prs_count: int = 0,
    oldest_pr_age_hours: float | None = None,
    open_issues_count: int = 0,
    oldest_issue_age_days: float | None = None,
    last_ci_success: bool | None = True,
    has_stale_dependencies: bool = False,
) -> RepoHealth:
    """Create a RepoHealth instance with sensible defaults.

    If `last_commit_at` is not provided but `commit_hours_ago` is,
    computes `last_commit_at` relative to now.
    """
    if last_commit_at is None and commit_hours_ago is not None:
        last_commit_at = datetime.now(UTC) - timedelta(hours=commit_hours_ago)

    return RepoHealth(
        last_commit_at=last_commit_at,
        open_prs_count=open_prs_count,
        oldest_pr_age_hours=oldest_pr_age_hours,
        open_issues_count=open_issues_count,
        oldest_issue_age_days=oldest_issue_age_days,
        last_ci_success=last_ci_success,
        has_stale_dependencies=has_stale_dependencies,
    )


def make_healthy_repo() -> RepoHealth:
    """Create a healthy repository state."""
    return make_repo_health(
        commit_hours_ago=1.0,
        last_ci_success=True,
        has_stale_dependencies=False,
    )


def make_unhealthy_repo() -> RepoHealth:
    """Create an unhealthy repository state."""
    return make_repo_health(
        commit_hours_ago=240.0,  # 10 days
        open_prs_count=5,
        oldest_pr_age_hours=100,
        open_issues_count=20,
        oldest_issue_age_days=30,
        last_ci_success=False,
        has_stale_dependencies=True,
    )
