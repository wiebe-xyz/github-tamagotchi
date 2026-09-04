"""Tests for the play-driven boredom mood signal."""

from datetime import UTC, datetime, timedelta

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.pet_care.boredom import (
    BOREDOM_MAX_HOURS,
    BOREDOM_MIN_HOURS,
    boredom_threshold_hours,
    is_bored,
)

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _pet(**overrides: object) -> Pet:
    defaults: dict[str, object] = {
        "repo_owner": "o",
        "repo_name": "r",
        "name": "P",
        "stage": PetStage.BABY.value,
        "mood": PetMood.CONTENT.value,
        "health": 50,
        "experience": 0,
        "created_at": NOW - timedelta(days=30),
        "last_played_at": None,
    }
    defaults.update(overrides)
    return Pet(**defaults)  # type: ignore[arg-type]


class TestBoredomThresholdHours:
    def test_lazy_pet_uses_max_hours(self) -> None:
        assert boredom_threshold_hours(0.0) == BOREDOM_MAX_HOURS

    def test_active_pet_uses_min_hours(self) -> None:
        assert boredom_threshold_hours(1.0) == BOREDOM_MIN_HOURS

    def test_midpoint_is_halfway_between(self) -> None:
        expected = (BOREDOM_MAX_HOURS + BOREDOM_MIN_HOURS) / 2
        assert boredom_threshold_hours(0.5) == expected

    def test_clamps_out_of_range_activity(self) -> None:
        assert boredom_threshold_hours(-1.0) == BOREDOM_MAX_HOURS
        assert boredom_threshold_hours(2.0) == BOREDOM_MIN_HOURS


class TestIsBored:
    def test_just_under_threshold_is_not_bored(self) -> None:
        pet = _pet(last_played_at=NOW - timedelta(hours=BOREDOM_MIN_HOURS - 0.1))
        assert is_bored(pet, activity=1.0, now=NOW) is False

    def test_at_threshold_is_not_bored(self) -> None:
        """Boundary itself is not yet bored -- strictly greater-than triggers it."""
        pet = _pet(last_played_at=NOW - timedelta(hours=BOREDOM_MIN_HOURS))
        assert is_bored(pet, activity=1.0, now=NOW) is False

    def test_just_over_threshold_is_bored(self) -> None:
        pet = _pet(last_played_at=NOW - timedelta(hours=BOREDOM_MIN_HOURS + 0.1))
        assert is_bored(pet, activity=1.0, now=NOW) is True

    def test_never_played_falls_back_to_created_at(self) -> None:
        """No last_played_at yet: a fresh hatchling gets a grace period from
        created_at instead of being instantly bored."""
        pet = _pet(created_at=NOW - timedelta(hours=1), last_played_at=None)
        assert is_bored(pet, activity=1.0, now=NOW) is False

    def test_never_played_and_old_creation_is_bored(self) -> None:
        pet = _pet(created_at=NOW - timedelta(hours=BOREDOM_MAX_HOURS + 1), last_played_at=None)
        assert is_bored(pet, activity=0.0, now=NOW) is True

    def test_naive_timestamps_are_compared_without_tzinfo(self) -> None:
        """DB round-trips can hand back naive datetimes; comparison must not raise."""
        naive_now = NOW.replace(tzinfo=None)
        pet = _pet(last_played_at=naive_now - timedelta(hours=BOREDOM_MIN_HOURS + 1))
        assert is_bored(pet, activity=1.0, now=NOW) is True
