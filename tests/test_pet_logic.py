"""Tests for pet logic."""

from datetime import UTC, datetime, timedelta

from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.github import RepoHealth
from github_tamagotchi.services.pet_logic import (
    calculate_health_delta,
    calculate_mood,
    get_next_stage,
)


def test_calculate_mood_happy_with_ci_success() -> None:
    """Pet should be dancing when CI is successful."""
    health = RepoHealth(
        last_commit_at=datetime.now(UTC),
        open_prs_count=0,
        oldest_pr_age_hours=None,
        open_issues_count=0,
        oldest_issue_age_days=None,
        last_ci_success=True,
        has_stale_dependencies=False,
    )
    mood = calculate_mood(health, current_health=100)
    assert mood == PetMood.DANCING


def test_calculate_mood_hungry_no_commits() -> None:
    """Pet should be hungry when no commits in 3+ days."""
    health = RepoHealth(
        last_commit_at=datetime.now(UTC) - timedelta(days=4),
        open_prs_count=0,
        oldest_pr_age_hours=None,
        open_issues_count=0,
        oldest_issue_age_days=None,
        last_ci_success=False,
        has_stale_dependencies=False,
    )
    mood = calculate_mood(health, current_health=100)
    assert mood == PetMood.HUNGRY


def test_calculate_mood_worried_old_pr() -> None:
    """Pet should be worried when PR is open > 48 hours."""
    health = RepoHealth(
        last_commit_at=datetime.now(UTC),
        open_prs_count=1,
        oldest_pr_age_hours=72,
        open_issues_count=0,
        oldest_issue_age_days=None,
        last_ci_success=False,
        has_stale_dependencies=False,
    )
    mood = calculate_mood(health, current_health=100)
    assert mood == PetMood.WORRIED


def test_calculate_mood_sick_stale_deps() -> None:
    """Pet should be sick when dependencies are stale."""
    health = RepoHealth(
        last_commit_at=datetime.now(UTC),
        open_prs_count=0,
        oldest_pr_age_hours=None,
        open_issues_count=0,
        oldest_issue_age_days=None,
        last_ci_success=True,
        has_stale_dependencies=True,
    )
    mood = calculate_mood(health, current_health=100)
    assert mood == PetMood.SICK


def test_get_next_stage_evolution() -> None:
    """Pet should evolve when experience threshold is met."""
    next_stage = get_next_stage(PetStage.EGG, experience=150)
    assert next_stage == PetStage.BABY


def test_get_next_stage_no_evolution() -> None:
    """Pet should not evolve when experience is below threshold."""
    next_stage = get_next_stage(PetStage.EGG, experience=50)
    assert next_stage == PetStage.EGG


def test_calculate_health_delta_positive() -> None:
    """Health should increase with recent commit and CI success."""
    health = RepoHealth(
        last_commit_at=datetime.now(UTC) - timedelta(hours=1),
        open_prs_count=0,
        oldest_pr_age_hours=None,
        open_issues_count=0,
        oldest_issue_age_days=None,
        last_ci_success=True,
        has_stale_dependencies=False,
    )
    delta = calculate_health_delta(health)
    assert delta > 0
