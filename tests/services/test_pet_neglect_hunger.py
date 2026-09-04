"""Tests for the neglect-hunger mechanic (fed_pet-based, appetite-scaled)."""

from datetime import UTC, datetime, timedelta

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.pet_care.neglect_hunger import (
    NEGLECT_HUNGER_MAX_HOURS,
    NEGLECT_HUNGER_MIN_HOURS,
    is_neglected_hungry,
    neglect_hunger_threshold_hours,
)

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


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
        "last_fed_at": None,
    }
    defaults.update(overrides)
    return Pet(**defaults)  # type: ignore[arg-type]


class TestNeglectHungerThresholdHours:
    def test_zero_appetite_is_max_hours(self) -> None:
        assert neglect_hunger_threshold_hours(0.0) == NEGLECT_HUNGER_MAX_HOURS

    def test_half_appetite_is_midpoint(self) -> None:
        expected = (NEGLECT_HUNGER_MAX_HOURS + NEGLECT_HUNGER_MIN_HOURS) / 2
        assert neglect_hunger_threshold_hours(0.5) == expected

    def test_full_appetite_is_min_hours(self) -> None:
        assert neglect_hunger_threshold_hours(1.0) == NEGLECT_HUNGER_MIN_HOURS

    def test_clamps_below_zero(self) -> None:
        assert neglect_hunger_threshold_hours(-0.5) == NEGLECT_HUNGER_MAX_HOURS

    def test_clamps_above_one(self) -> None:
        assert neglect_hunger_threshold_hours(1.5) == NEGLECT_HUNGER_MIN_HOURS


class TestIsNeglectedHungry:
    def test_just_under_threshold_not_hungry(self) -> None:
        threshold = neglect_hunger_threshold_hours(1.0)
        pet = _pet(last_fed_at=NOW - timedelta(hours=threshold - 0.01))
        assert is_neglected_hungry(pet, 1.0, NOW) is False

    def test_at_threshold_not_hungry(self) -> None:
        """Boundary is a strict '>' — exactly at the threshold is not yet hungry."""
        threshold = neglect_hunger_threshold_hours(1.0)
        pet = _pet(last_fed_at=NOW - timedelta(hours=threshold))
        assert is_neglected_hungry(pet, 1.0, NOW) is False

    def test_just_over_threshold_is_hungry(self) -> None:
        threshold = neglect_hunger_threshold_hours(1.0)
        pet = _pet(last_fed_at=NOW - timedelta(hours=threshold + 0.01))
        assert is_neglected_hungry(pet, 1.0, NOW) is True

    def test_never_fed_falls_back_to_created_at(self) -> None:
        """Never-fed pet uses created_at as the reference, giving it a grace
        period from hatching rather than instant hunger."""
        created = NOW - timedelta(hours=NEGLECT_HUNGER_MAX_HOURS - 1)
        pet = _pet(last_fed_at=None, created_at=created)
        assert is_neglected_hungry(pet, 0.0, NOW) is False

    def test_never_fed_and_past_grace_period_is_hungry(self) -> None:
        created = NOW - timedelta(hours=NEGLECT_HUNGER_MAX_HOURS + 1)
        pet = _pet(last_fed_at=None, created_at=created)
        assert is_neglected_hungry(pet, 0.0, NOW) is True

    def test_light_eater_gets_longer_grace_than_hungry_trait(self) -> None:
        hours_since_fed = (NEGLECT_HUNGER_MIN_HOURS + NEGLECT_HUNGER_MAX_HOURS) / 2
        pet = _pet(last_fed_at=NOW - timedelta(hours=hours_since_fed))
        assert is_neglected_hungry(pet, 0.0, NOW) is False
        assert is_neglected_hungry(pet, 1.0, NOW) is True
