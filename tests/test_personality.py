"""Tests for pet personality traits."""

from datetime import UTC, datetime, timedelta

import pytest

from github_tamagotchi.models.pet import PetMood
from github_tamagotchi.services.github import RepoHealth
from github_tamagotchi.services.pet_logic import (
    PetPersonality,
    generate_personality,
    get_personality_message,
)


class TestGeneratePersonality:
    """Tests for generate_personality function."""

    def test_returns_pet_personality(self) -> None:
        """Should return a PetPersonality instance."""
        result = generate_personality("owner", "repo")
        assert isinstance(result, PetPersonality)

    def test_all_traits_in_range(self) -> None:
        """All traits should be in [0.0, 1.0]."""
        p = generate_personality("owner", "repo")
        for trait in (p.activity, p.sociability, p.bravery, p.tidiness, p.appetite):
            assert 0.0 <= trait <= 1.0

    def test_deterministic_without_health(self) -> None:
        """Same repo should always get same personality."""
        p1 = generate_personality("myorg", "myrepo")
        p2 = generate_personality("myorg", "myrepo")
        assert p1.activity == p2.activity
        assert p1.sociability == p2.sociability
        assert p1.bravery == p2.bravery
        assert p1.tidiness == p2.tidiness
        assert p1.appetite == p2.appetite

    def test_different_repos_get_different_personalities(self) -> None:
        """Different repos should generally get different personalities."""
        p1 = generate_personality("owner", "repo-a")
        p2 = generate_personality("owner", "repo-b")
        # At least one trait should differ
        traits1 = (p1.activity, p1.sociability, p1.bravery, p1.tidiness, p1.appetite)
        traits2 = (p2.activity, p2.sociability, p2.bravery, p2.tidiness, p2.appetite)
        assert traits1 != traits2

    def test_recent_commit_nudges_activity_high(self) -> None:
        """A repo with very recent commits should have higher activity."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=1),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=None,
            has_stale_dependencies=False,
        )
        p = generate_personality("owner", "repo", health)
        # Recent commit nudges activity high: activity = base * 0.4 + 0.6
        # So activity >= 0.6 at minimum
        assert p.activity >= 0.6

    def test_old_commit_nudges_activity_low(self) -> None:
        """A repo with no recent commits (>72h) should have lower activity."""
        health = RepoHealth(
            last_commit_at=datetime.now(UTC) - timedelta(hours=100),
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=None,
            has_stale_dependencies=False,
        )
        p = generate_personality("owner", "repo", health)
        # Old commit nudges activity low: activity = base * 0.4 => max 0.4
        assert p.activity <= 0.4

    def test_no_old_prs_nudges_bravery_high(self) -> None:
        """No old PRs (or fast PR merging) should nudge bravery high."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,  # No PRs at all = brave
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=None,
            has_stale_dependencies=False,
        )
        p = generate_personality("owner", "repo", health)
        assert p.bravery >= 0.6

    def test_old_prs_nudge_bravery_low(self) -> None:
        """Very old open PRs should nudge bravery low (cautious)."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=3,
            oldest_pr_age_hours=100,  # Very old PR
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=None,
            has_stale_dependencies=False,
        )
        p = generate_personality("owner", "repo", health)
        assert p.bravery <= 0.4

    def test_zero_issues_nudges_tidiness_high(self) -> None:
        """Zero open issues should nudge tidiness high (neat)."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=0,
            oldest_issue_age_days=None,
            last_ci_success=None,
            has_stale_dependencies=False,
        )
        p = generate_personality("owner", "repo", health)
        assert p.tidiness >= 0.6

    def test_many_issues_nudge_tidiness_low(self) -> None:
        """Many open issues (>10) should nudge tidiness low (messy)."""
        health = RepoHealth(
            last_commit_at=None,
            open_prs_count=0,
            oldest_pr_age_hours=None,
            open_issues_count=15,
            oldest_issue_age_days=5.0,
            last_ci_success=None,
            has_stale_dependencies=False,
        )
        p = generate_personality("owner", "repo", health)
        assert p.tidiness <= 0.4

    def test_traits_rounded_to_3_decimals(self) -> None:
        """Traits should be rounded to 3 decimal places."""
        p = generate_personality("owner", "repo")
        for trait in (p.activity, p.sociability, p.bravery, p.tidiness, p.appetite):
            assert round(trait, 3) == trait


class TestGetPersonalityMessage:
    """Tests for get_personality_message function."""

    def test_active_pet_hungry_message(self) -> None:
        """Active pet should get restless message when hungry."""
        personality = PetPersonality(
            activity=0.8,
            sociability=0.5,
            bravery=0.5,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("Chippy", personality, PetMood.HUNGRY)
        assert msg is not None
        assert "Chippy" in msg
        assert "pacing" in msg or "action" in msg

    def test_lazy_pet_hungry_message(self) -> None:
        """Lazy pet should get relaxed message when hungry."""
        personality = PetPersonality(
            activity=0.2,
            sociability=0.5,
            bravery=0.5,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("Chippy", personality, PetMood.HUNGRY)
        assert msg is not None
        assert "Chippy" in msg
        assert "quiet" in msg or "snack" in msg

    def test_brave_pet_worried_message(self) -> None:
        """Brave pet should get bold message when worried about PRs."""
        personality = PetPersonality(
            activity=0.5,
            sociability=0.5,
            bravery=0.8,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("Chippy", personality, PetMood.WORRIED)
        assert msg is not None
        assert "Chippy" in msg
        assert "PR" in msg or "merge" in msg

    def test_cautious_pet_worried_message(self) -> None:
        """Cautious pet should get hiding message when worried about PRs."""
        personality = PetPersonality(
            activity=0.5,
            sociability=0.5,
            bravery=0.2,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("Chippy", personality, PetMood.WORRIED)
        assert msg is not None
        assert "Chippy" in msg
        assert "hiding" in msg or "desk" in msg or "PR" in msg

    def test_happy_mood_returns_none(self) -> None:
        """Happy mood should return None (no personality message needed)."""
        personality = PetPersonality(
            activity=0.8,
            sociability=0.8,
            bravery=0.8,
            tidiness=0.8,
            appetite=0.8,
        )
        msg = get_personality_message("Chippy", personality, PetMood.HAPPY)
        assert msg is None

    def test_content_mood_returns_none(self) -> None:
        """Content mood should return None."""
        personality = PetPersonality(
            activity=0.5,
            sociability=0.5,
            bravery=0.5,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("Chippy", personality, PetMood.CONTENT)
        assert msg is None

    def test_dancing_mood_returns_none(self) -> None:
        """Dancing mood should return None."""
        personality = PetPersonality(
            activity=0.5,
            sociability=0.5,
            bravery=0.5,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("Chippy", personality, PetMood.DANCING)
        assert msg is None

    @pytest.mark.parametrize("mood", [PetMood.SICK, PetMood.LONELY])
    def test_other_moods_return_none(self, mood: PetMood) -> None:
        """Moods without personality messages should return None."""
        personality = PetPersonality(
            activity=0.5,
            sociability=0.5,
            bravery=0.5,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("Chippy", personality, mood)
        assert msg is None

    def test_message_includes_pet_name(self) -> None:
        """All personality messages should include the pet's name."""
        personality = PetPersonality(
            activity=0.8,
            sociability=0.5,
            bravery=0.5,
            tidiness=0.5,
            appetite=0.5,
        )
        msg = get_personality_message("FancyPet", personality, PetMood.HUNGRY)
        assert msg is not None
        assert "FancyPet" in msg
