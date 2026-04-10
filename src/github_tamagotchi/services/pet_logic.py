"""Pet state management and evolution logic."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from github_tamagotchi.models.pet import PetMood, PetSkin, PetStage
from github_tamagotchi.services.github import RepoHealth

if TYPE_CHECKING:
    from github_tamagotchi.models.pet import Pet

# Thresholds for pet state changes
HUNGRY_THRESHOLD_DAYS = 3  # No commits in 3 days = hungry
WORRIED_THRESHOLD_HOURS = 48  # PR open > 48 hours = worried
LONELY_THRESHOLD_DAYS = 7  # Issue unanswered > 1 week = lonely

# Security alert health penalties per poll cycle
SECURITY_HEALTH_PENALTY = {
    "critical": 20,
    "high": 10,
    "medium": 5,
    "low": 2,
}

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

    # Check for sick (critical/high security alerts — highest priority)
    if health.security_alerts_critical > 0 or health.security_alerts_high > 0:
        return PetMood.SICK

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

    # Release frequency bonus: +2 per release in last 30d, capped at +10
    delta += min(health.release_count_30d * 2, 10)

    # Contributor count bonus: +1 per unique contributor in last 90d, capped at +8
    delta += min(health.contributor_count, 8)

    # Negative effects
    if health.has_stale_dependencies:
        delta -= 10
    if health.oldest_pr_age_hours and health.oldest_pr_age_hours > WORRIED_THRESHOLD_HOURS:
        delta -= 5
    if health.oldest_issue_age_days and health.oldest_issue_age_days > LONELY_THRESHOLD_DAYS:
        delta -= 5

    # Security alert penalties (capped per severity to avoid instant death)
    if health.security_alerts_critical > 0:
        delta -= min(health.security_alerts_critical * SECURITY_HEALTH_PENALTY["critical"], 40)
    if health.security_alerts_high > 0:
        delta -= min(health.security_alerts_high * SECURITY_HEALTH_PENALTY["high"], 20)
    if health.security_alerts_medium > 0:
        delta -= min(health.security_alerts_medium * SECURITY_HEALTH_PENALTY["medium"], 10)
    if health.security_alerts_low > 0:
        delta -= min(health.security_alerts_low * SECURITY_HEALTH_PENALTY["low"], 4)

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


def update_commit_streak(pet: "Pet", health: RepoHealth, now: datetime) -> None:
    """Update commit streak fields on the pet based on recent commit activity.

    A streak counts days with at least one commit. Uses a 48-hour window to
    be generous with polling frequency variations.
    """
    if health.last_commit_at is not None:
        hours_since_commit = (now - health.last_commit_at).total_seconds() / 3600
        if hours_since_commit <= 48:
            # There's been a recent commit — update the streak
            if pet.last_streak_date is None:
                # First ever streak day
                pet.commit_streak = 1
            else:
                hours_since_last_streak = (now - pet.last_streak_date).total_seconds() / 3600
                if hours_since_last_streak > 48:
                    # Gap too large — restart streak
                    pet.commit_streak = 1
                else:
                    # Continuing streak
                    pet.commit_streak += 1
            pet.last_streak_date = now
        else:
            # No recent commit — possibly break the streak
            if pet.last_streak_date is not None:
                hours_since_last_streak = (now - pet.last_streak_date).total_seconds() / 3600
                if hours_since_last_streak > 48:
                    pet.commit_streak = 0
    else:
        # No commit data at all — break streak if stale
        if pet.last_streak_date is not None:
            hours_since_last_streak = (now - pet.last_streak_date).total_seconds() / 3600
            if hours_since_last_streak > 48:
                pet.commit_streak = 0

    pet.longest_streak = max(pet.longest_streak, pet.commit_streak)


# Death thresholds
DEATH_GRACE_PERIOD_DAYS = 7  # Days at 0 health before death
ABANDONMENT_THRESHOLD_DAYS = 90  # Days without any activity before abandonment death


def update_grace_period(pet: "Pet", now: datetime) -> None:
    """Set or clear grace_period_started based on current health.

    If health is 0, record the start of the grace period (if not already set).
    If health is above 0, clear the grace period.
    """
    if pet.health == 0:
        if pet.grace_period_started is None:
            pet.grace_period_started = now
    else:
        pet.grace_period_started = None


def check_death_conditions(pet: "Pet", now: datetime) -> tuple[bool, str | None]:
    """Check whether the pet should die and return the cause.

    Returns (should_die, cause) where cause is one of:
      - "neglect"     — health has been at 0 for 7+ days
      - "abandonment" — no activity for 90 days

    Returns (False, None) if the pet should stay alive.
    """
    # Abandonment: no activity (last_checked_at or last_fed_at) for 90 days
    last_activity = pet.last_checked_at or pet.last_fed_at or pet.created_at
    # Normalise: if naive datetime, compare against naive now
    compare_now = now.replace(tzinfo=None) if last_activity.tzinfo is None else now
    days_inactive = (compare_now - last_activity).total_seconds() / 86400
    if days_inactive >= ABANDONMENT_THRESHOLD_DAYS:
        return True, "abandonment"

    # Neglect: health at 0 for 7+ days
    if pet.grace_period_started is not None:
        grace_start = pet.grace_period_started
        compare_now = now.replace(tzinfo=None) if grace_start.tzinfo is None else now
        days_at_zero = (compare_now - grace_start).total_seconds() / 86400
        if days_at_zero >= DEATH_GRACE_PERIOD_DAYS:
            return True, "neglect"

    return False, None

# Skin unlock conditions keyed by skin variant
SKIN_UNLOCK_CONDITIONS: dict[PetSkin, str] = {
    PetSkin.CLASSIC: "Default skin, always available",
    PetSkin.ROBOT: "Reach Adult stage",
    PetSkin.DRAGON: "Reach Elder stage",
    PetSkin.GHOST: "Recover from critical health (<5) three times",
}


def get_unlocked_skins(pet: "Pet") -> list[PetSkin]:
    """Return the list of skins unlocked for the given pet."""
    unlocked = [PetSkin.CLASSIC]

    stage = PetStage(pet.stage)

    if stage in (PetStage.ADULT, PetStage.ELDER):
        unlocked.append(PetSkin.ROBOT)

    if stage == PetStage.ELDER:
        unlocked.append(PetSkin.DRAGON)

    if pet.low_health_recoveries >= 3:
        unlocked.append(PetSkin.GHOST)

    return unlocked
