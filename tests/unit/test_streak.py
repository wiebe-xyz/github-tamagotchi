"""Tests for commit streak tracking logic."""

from datetime import UTC, datetime, timedelta

from github_tamagotchi.services.pet_logic import update_commit_streak
from tests.factories import make_pet, make_repo_health  # noqa: E402

NOW = datetime(2026, 4, 9, 12, 0, 0, tzinfo=UTC)

# Convenient helpers relative to NOW
def _hours_ago(h: float) -> datetime:
    return NOW - timedelta(hours=h)


class TestUpdateCommitStreak:
    """Tests for update_commit_streak function."""

    def test_first_commit_sets_streak_to_one(self) -> None:
        """First commit ever should set streak to 1."""
        pet = make_pet(commit_streak=0, longest_streak=0, last_streak_date=None)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 1

    def test_first_commit_sets_last_streak_date(self) -> None:
        """First commit should set last_streak_date to now."""
        pet = make_pet(commit_streak=0, longest_streak=0, last_streak_date=None)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.last_streak_date == NOW

    def test_commit_within_48h_increments_streak(self) -> None:
        """Commit within 48h of last streak date increments the streak."""
        last_date = _hours_ago(24)
        pet = make_pet(commit_streak=3, longest_streak=3, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 4

    def test_yesterday_streak_date_increments(self) -> None:
        """Streak updated yesterday (1 calendar day ago) increments today."""
        # 35h ago from Apr 9 12:00 = Apr 8 01:00 — still the previous calendar day
        last_date = _hours_ago(35)
        pet = make_pet(commit_streak=5, longest_streak=5, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 6

    def test_same_day_poll_does_not_double_count(self) -> None:
        """Multiple polls on the same day don't increment streak more than once."""
        last_date = _hours_ago(2)  # Same calendar day
        pet = make_pet(commit_streak=5, longest_streak=5, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        # Still 5 — same day was already counted
        assert pet.commit_streak == 5

    def test_gap_over_48h_resets_streak_to_one(self) -> None:
        """Gap > 48 hours with new commit resets streak to 1."""
        last_date = _hours_ago(73)
        pet = make_pet(commit_streak=10, longest_streak=10, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 1

    def test_no_recent_commit_resets_streak_when_stale(self) -> None:
        """No recent commit (>48h ago) resets streak if last streak date is also stale."""
        last_date = _hours_ago(73)
        pet = make_pet(commit_streak=5, longest_streak=5, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=_hours_ago(72), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 0

    def test_no_recent_commit_preserves_streak_if_not_stale(self) -> None:
        """Streak is preserved when last streak date is still within 48h window."""
        last_date = _hours_ago(12)
        pet = make_pet(commit_streak=4, longest_streak=4, last_streak_date=last_date)
        # Commit is 50h ago — outside the 48h window
        health = make_repo_health(last_commit_at=_hours_ago(50), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        # Streak preserved because last_streak_date is still fresh
        assert pet.commit_streak == 4

    def test_no_commit_data_resets_streak_when_stale(self) -> None:
        """No commit data at all resets streak if last streak date is stale."""
        last_date = _hours_ago(73)
        pet = make_pet(commit_streak=7, longest_streak=7, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=None, commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 0

    def test_longest_streak_updated_when_current_exceeds(self) -> None:
        """longest_streak should be updated when commit_streak surpasses it."""
        last_date = _hours_ago(24)
        pet = make_pet(commit_streak=9, longest_streak=9, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 10
        assert pet.longest_streak == 10

    def test_longest_streak_preserved_when_streak_resets(self) -> None:
        """longest_streak should not decrease when current streak resets."""
        last_date = _hours_ago(73)
        pet = make_pet(commit_streak=5, longest_streak=20, last_streak_date=last_date)
        health = make_repo_health(last_commit_at=_hours_ago(1), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 1
        assert pet.longest_streak == 20

    def test_zero_streak_longest_streak_stays_zero(self) -> None:
        """With no streak history and no commit, longest_streak stays at 0."""
        pet = make_pet(commit_streak=0, longest_streak=0, last_streak_date=None)
        health = make_repo_health(last_commit_at=None, commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 0
        assert pet.longest_streak == 0

    def test_commit_at_exact_48h_boundary_counts(self) -> None:
        """Commit exactly 48h ago should count as recent (boundary inclusive)."""
        pet = make_pet(commit_streak=0, longest_streak=0, last_streak_date=None)
        health = make_repo_health(last_commit_at=_hours_ago(48), commit_hours_ago=None)
        update_commit_streak(pet, health, NOW)
        assert pet.commit_streak == 1
