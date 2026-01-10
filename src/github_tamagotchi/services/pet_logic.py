"""Pet state management and evolution logic."""

from datetime import UTC, datetime

from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.github import RepoHealth


# Thresholds for pet state changes
HUNGRY_THRESHOLD_DAYS = 3  # No commits in 3 days = hungry
WORRIED_THRESHOLD_HOURS = 48  # PR open > 48 hours = worried
LONELY_THRESHOLD_DAYS = 7  # Issue unanswered > 1 week = lonely

# Experience thresholds for evolution
EVOLUTION_THRESHOLDS = {
    PetStage.EGG: 0,
    PetStage.BABY: 100,
    PetStage.CHILD: 500,
    PetStage.TEEN: 1500,
    PetStage.ADULT: 5000,
    PetStage.ELDER: 15000,
}


def calculate_mood(health: RepoHealth, current_health: int) -> PetMood:
    """Determine pet mood based on repository health metrics."""
    now = datetime.now(UTC)

    # Check for sick (stale dependencies)
    if health.has_stale_dependencies:
        return PetMood.SICK

    # Check for hungry (no recent commits)
    if health.last_commit_at:
        days_since_commit = (now - health.last_commit_at).total_seconds() / 86400
        if days_since_commit > HUNGRY_THRESHOLD_DAYS:
            return PetMood.HUNGRY

    # Check for worried (old PRs)
    if health.oldest_pr_age_hours and health.oldest_pr_age_hours > WORRIED_THRESHOLD_HOURS:
        return PetMood.WORRIED

    # Check for lonely (old issues)
    if health.oldest_issue_age_days and health.oldest_issue_age_days > LONELY_THRESHOLD_DAYS:
        return PetMood.LONELY

    # Check for dancing (successful CI)
    if health.last_ci_success:
        return PetMood.DANCING

    # Default states based on health
    if current_health >= 80:
        return PetMood.HAPPY
    return PetMood.CONTENT


def calculate_health_delta(health: RepoHealth) -> int:
    """Calculate health change based on repo metrics."""
    delta = 0

    # Positive effects
    if health.last_ci_success:
        delta += 5  # Successful CI
    if health.last_commit_at:
        now = datetime.now(UTC)
        hours_since_commit = (now - health.last_commit_at).total_seconds() / 3600
        if hours_since_commit < 24:
            delta += 10  # Recent commit = feeding

    # Negative effects
    if health.has_stale_dependencies:
        delta -= 10
    if health.oldest_pr_age_hours and health.oldest_pr_age_hours > WORRIED_THRESHOLD_HOURS:
        delta -= 5
    if health.oldest_issue_age_days and health.oldest_issue_age_days > LONELY_THRESHOLD_DAYS:
        delta -= 5

    return delta


def calculate_experience(health: RepoHealth) -> int:
    """Calculate experience gained from repo activity."""
    exp = 0

    # Experience from activity
    if health.last_ci_success:
        exp += 10
    if health.last_commit_at:
        now = datetime.now(UTC)
        hours_since_commit = (now - health.last_commit_at).total_seconds() / 3600
        if hours_since_commit < 24:
            exp += 20  # Recent commit

    return exp


def get_next_stage(current_stage: PetStage, experience: int) -> PetStage:
    """Determine if pet should evolve to next stage."""
    stages = list(PetStage)
    current_idx = stages.index(current_stage)

    if current_idx >= len(stages) - 1:
        return current_stage  # Already at max stage

    next_stage = stages[current_idx + 1]
    if experience >= EVOLUTION_THRESHOLDS[next_stage]:
        return next_stage

    return current_stage
