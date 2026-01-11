"""Tests for pet logic."""

from datetime import UTC, datetime, timedelta

import pytest

from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.github import RepoHealth
from github_tamagotchi.services.pet_logic import (
    EVOLUTION_THRESHOLDS,
    HUNGRY_THRESHOLD_DAYS,
    LONELY_THRESHOLD_DAYS,
    WORRIED_THRESHOLD_HOURS,
    calculate_experience,
    calculate_health_delta,
    calculate_mood,
    get_next_stage,
)


class TestCalculateMood:
    """Tests for calculate_mood function."""

    def test_sick_when_stale_dependencies(self) -> None:
        """Pet should be sick when dependencies are stale (highest priority)."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=True,
        )
        assert calculate_mood(health, current_health=100) == PetMood.SICK

    def test_hungry_when_no_recent_commits(self) -> None:
        """Pet should be hungry when no commits in 3+ days."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(days=HUNGRY_THRESHOLD_DAYS + 1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_mood(health, current_health=100) == PetMood.HUNGRY

    def test_worried_when_old_prs(self) -> None:
        """Pet should be worried when PR is open > 48 hours."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC),
            open_prs_count=1,
            oldest_pr_age_hours=WORRIED_THRESHOLD_HOURS + 10,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_mood(health, current_health=100) == PetMood.WORRIED

    def test_lonely_when_old_issues(self) -> None:
        """Pet should be lonely when issue is unanswered > 7 days."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=5,
            oldest_issue_age_days=LONELY_THRESHOLD_DAYS + 1,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_mood(health, current_health=100) == PetMood.LONELY

    def test_dancing_when_ci_success(self) -> None:
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
        assert calculate_mood(health, current_health=100) == PetMood.DANCING

    def test_happy_when_high_health_no_ci_info(self) -> None:
        """Pet should be happy when health >= 80 and no CI info."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_mood(health, current_health=80) == PetMood.HAPPY

    def test_content_when_low_health_no_issues(self) -> None:
        """Pet should be content when health < 80 but no issues."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_mood(health, current_health=50) == PetMood.CONTENT

    def test_mood_priority_sick_over_hungry(self) -> None:
        """Sick should take priority over hungry."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(days=10),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=True,
        )
        assert calculate_mood(health, current_health=100) == PetMood.SICK

    def test_no_commit_timestamp_skips_hungry_check(self) -> None:
        """When last_commit_at is None, hungry check is skipped."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )
        assert calculate_mood(health, current_health=100) == PetMood.DANCING


class TestCalculateHealthDelta:
    """Tests for calculate_health_delta function."""

    def test_positive_delta_with_ci_success(self) -> None:
        """Health should increase with CI success."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )
        assert calculate_health_delta(health) == 5

    def test_positive_delta_with_recent_commit(self) -> None:
        """Health should increase with recent commit."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_health_delta(health) == 10

    def test_combined_positive_effects(self) -> None:
        """Health should combine positive effects."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )
        # +5 for CI + +10 for recent commit = 15
        assert calculate_health_delta(health) == 15

    def test_negative_delta_with_stale_deps(self) -> None:
        """Health should decrease with stale dependencies."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=True,
        )
        assert calculate_health_delta(health) == -10

    def test_negative_delta_with_old_pr(self) -> None:
        """Health should decrease with old PRs."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=1,
            oldest_pr_age_hours=WORRIED_THRESHOLD_HOURS + 10,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_health_delta(health) == -5

    def test_negative_delta_with_old_issues(self) -> None:
        """Health should decrease with old issues."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=5,
            oldest_issue_age_days=LONELY_THRESHOLD_DAYS + 1,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_health_delta(health) == -5

    def test_combined_negative_effects(self) -> None:
        """Health should combine all negative effects."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=1,
            oldest_pr_age_hours=WORRIED_THRESHOLD_HOURS + 10,
            open_issues_count=5,
            oldest_issue_age_days=LONELY_THRESHOLD_DAYS + 1,
            last_ci_success=False,
            has_stale_dependencies=True,
        )
        # -10 for stale deps + -5 for old PR + -5 for old issue = -20
        assert calculate_health_delta(health) == -20

    def test_zero_delta_with_no_activity(self) -> None:
        """Health should not change with no activity."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_health_delta(health) == 0

    def test_old_commit_no_bonus(self) -> None:
        """Commits older than 24 hours should not give bonus."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=25),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_health_delta(health) == 0


class TestCalculateExperience:
    """Tests for calculate_experience function."""

    def test_experience_with_ci_success(self) -> None:
        """Should gain experience from CI success."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )
        assert calculate_experience(health) == 10

    def test_experience_with_recent_commit(self) -> None:
        """Should gain experience from recent commit."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_experience(health) == 20

    def test_experience_combined(self) -> None:
        """Should combine experience from multiple sources."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=True,
            has_stale_dependencies=False,
        )
        # 10 for CI + 20 for recent commit = 30
        assert calculate_experience(health) == 30

    def test_no_experience_with_old_commit(self) -> None:
        """Should not gain commit experience with old commit."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=25),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_experience(health) == 0

    def test_no_experience_with_no_activity(self) -> None:
        """Should not gain experience with no activity."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=False,
            has_stale_dependencies=False,
        )
        assert calculate_experience(health) == 0


class TestGetNextStage:
    """Tests for get_next_stage function."""

    def test_egg_to_baby_evolution(self) -> None:
        """Pet should evolve from egg to baby at threshold."""
        threshold = EVOLUTION_THRESHOLDS[PetStage.BABY]
        assert get_next_stage(PetStage.EGG, threshold) == PetStage.BABY

    def test_baby_to_child_evolution(self) -> None:
        """Pet should evolve from baby to child at threshold."""
        threshold = EVOLUTION_THRESHOLDS[PetStage.CHILD]
        assert get_next_stage(PetStage.BABY, threshold) == PetStage.CHILD

    def test_child_to_teen_evolution(self) -> None:
        """Pet should evolve from child to teen at threshold."""
        threshold = EVOLUTION_THRESHOLDS[PetStage.TEEN]
        assert get_next_stage(PetStage.CHILD, threshold) == PetStage.TEEN

    def test_teen_to_adult_evolution(self) -> None:
        """Pet should evolve from teen to adult at threshold."""
        threshold = EVOLUTION_THRESHOLDS[PetStage.ADULT]
        assert get_next_stage(PetStage.TEEN, threshold) == PetStage.ADULT

    def test_adult_to_elder_evolution(self) -> None:
        """Pet should evolve from adult to elder at threshold."""
        threshold = EVOLUTION_THRESHOLDS[PetStage.ELDER]
        assert get_next_stage(PetStage.ADULT, threshold) == PetStage.ELDER

    def test_elder_stays_elder(self) -> None:
        """Elder pet should not evolve further."""
        assert get_next_stage(PetStage.ELDER, 999999) == PetStage.ELDER

    def test_no_evolution_below_threshold(self) -> None:
        """Pet should not evolve if below threshold."""
        threshold = EVOLUTION_THRESHOLDS[PetStage.BABY]
        assert get_next_stage(PetStage.EGG, threshold - 1) == PetStage.EGG

    @pytest.mark.parametrize(
        "stage,exp,expected",
        [
            (PetStage.EGG, 0, PetStage.EGG),
            (PetStage.EGG, 99, PetStage.EGG),
            (PetStage.EGG, 100, PetStage.BABY),
            (PetStage.BABY, 499, PetStage.BABY),
            (PetStage.BABY, 500, PetStage.CHILD),
        ],
    )
    def test_evolution_boundary_cases(
        self, stage: PetStage, exp: int, expected: PetStage
    ) -> None:
        """Test evolution at exact threshold boundaries."""
        assert get_next_stage(stage, exp) == expected
