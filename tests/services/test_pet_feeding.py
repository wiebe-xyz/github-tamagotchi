"""Tests for the feed-vs-exercise weight mechanic."""

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.pet_feeding import (
    CHUBBY_THRESHOLD,
    FAT_THRESHOLD,
    MIN_WEIGHT,
    apply_exercise_decay,
    apply_feed,
    nudge_mood_happier,
    weight_label,
)


def _pet(**overrides: object) -> Pet:
    defaults: dict[str, object] = {
        "repo_owner": "o",
        "repo_name": "r",
        "name": "P",
        "stage": PetStage.BABY.value,
        "mood": PetMood.CONTENT.value,
        "health": 50,
        "experience": 0,
        "weight": 50.0,
    }
    defaults.update(overrides)
    return Pet(**defaults)  # type: ignore[arg-type]


class TestWeightLabel:
    def test_below_chubby_is_trim(self) -> None:
        assert weight_label(CHUBBY_THRESHOLD - 1) == "trim"

    def test_between_thresholds_is_chubby(self) -> None:
        assert weight_label(CHUBBY_THRESHOLD) == "chubby"
        assert weight_label(FAT_THRESHOLD - 1) == "chubby"

    def test_at_or_above_fat_threshold_is_fat(self) -> None:
        assert weight_label(FAT_THRESHOLD) == "fat"
        assert weight_label(FAT_THRESHOLD + 50) == "fat"


class TestApplyFeed:
    def test_normal_feed_raises_weight_and_health(self) -> None:
        pet = _pet(health=50, weight=50.0)
        result = apply_feed(pet)

        assert pet.weight == 65.0
        assert pet.health == 53
        assert result.health_change == 3
        assert result.overfed is False

    def test_health_caps_at_100(self) -> None:
        pet = _pet(health=99, weight=50.0)
        result = apply_feed(pet)

        assert pet.health == 100
        assert result.health_change == 1

    def test_already_fat_pet_gets_no_health_and_turns_sick(self) -> None:
        pet = _pet(health=50, weight=FAT_THRESHOLD, mood=PetMood.HAPPY.value)
        result = apply_feed(pet)

        assert pet.health == 50  # unchanged
        assert result.health_change == 0
        assert result.overfed is True
        assert pet.mood == PetMood.SICK.value

    def test_weight_gain_is_uncapped(self) -> None:
        """Feeding a fat pet again keeps raising weight even though health
        doesn't move — there's no ceiling, so it can go from fat to fatter."""
        pet = _pet(weight=FAT_THRESHOLD + 10)
        before = pet.weight
        apply_feed(pet)
        assert pet.weight > before


class TestApplyExerciseDecay:
    def test_lowers_weight(self) -> None:
        pet = _pet(weight=80.0)
        lost = apply_exercise_decay(pet)
        assert pet.weight == 70.0
        assert lost == 10.0

    def test_floors_at_min_weight(self) -> None:
        pet = _pet(weight=MIN_WEIGHT + 2)
        apply_exercise_decay(pet)
        assert pet.weight == MIN_WEIGHT

        # Further decay from the floor loses nothing more.
        lost = apply_exercise_decay(pet)
        assert pet.weight == MIN_WEIGHT
        assert lost == 0.0


class TestNudgeMoodHappier:
    def test_moves_bad_mood_toward_content(self) -> None:
        pet = _pet(mood=PetMood.LONELY.value)
        changed = nudge_mood_happier(pet)
        assert changed is True
        assert pet.mood == PetMood.CONTENT.value

    def test_content_moves_to_happy(self) -> None:
        pet = _pet(mood=PetMood.CONTENT.value)
        assert nudge_mood_happier(pet) is True
        assert pet.mood == PetMood.HAPPY.value

    def test_happy_does_not_advance_to_dancing(self) -> None:
        """Dancing is reserved for a real health win, not a check-in."""
        pet = _pet(mood=PetMood.HAPPY.value)
        assert nudge_mood_happier(pet) is False
        assert pet.mood == PetMood.HAPPY.value

    def test_dancing_is_left_alone(self) -> None:
        pet = _pet(mood=PetMood.DANCING.value)
        assert nudge_mood_happier(pet) is False
        assert pet.mood == PetMood.DANCING.value
