"""Tests for the mess mechanic."""

from datetime import UTC, datetime

from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.pet_care.mess import (
    MESS_DIRTY_THRESHOLD,
    MESS_DIRTY_THRESHOLD_MAX,
    MESS_DIRTY_THRESHOLD_MIN,
    add_mess,
    clean_pet,
    is_dirty,
    mess_dirty_threshold,
    mess_label,
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
        "mess_level": 0,
    }
    defaults.update(overrides)
    return Pet(**defaults)  # type: ignore[arg-type]


class TestAddMess:
    def test_increments_mess_level(self) -> None:
        pet = _pet(mess_level=0)
        add_mess(pet)
        assert pet.mess_level == 1

    def test_accumulates_across_calls(self) -> None:
        pet = _pet(mess_level=0)
        add_mess(pet)
        add_mess(pet)
        add_mess(pet)
        assert pet.mess_level == 3


class TestIsDirty:
    def test_just_under_threshold_is_not_dirty(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD - 1)
        assert is_dirty(pet, 0.5) is False

    def test_at_threshold_is_dirty(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD)
        assert is_dirty(pet, 0.5) is True

    def test_just_over_threshold_is_dirty(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD + 1)
        assert is_dirty(pet, 0.5) is True


class TestMessDirtyThreshold:
    def test_midpoint_matches_flat_threshold(self) -> None:
        assert mess_dirty_threshold(0.5) == MESS_DIRTY_THRESHOLD

    def test_messy_tolerates_the_most(self) -> None:
        assert mess_dirty_threshold(0.0) == MESS_DIRTY_THRESHOLD_MAX

    def test_neat_tolerates_the_least(self) -> None:
        assert mess_dirty_threshold(1.0) == MESS_DIRTY_THRESHOLD_MIN

    def test_clamps_out_of_range_values(self) -> None:
        assert mess_dirty_threshold(-1.0) == mess_dirty_threshold(0.0)
        assert mess_dirty_threshold(2.0) == mess_dirty_threshold(1.0)

    def test_never_below_the_floor(self) -> None:
        assert mess_dirty_threshold(1.0) >= MESS_DIRTY_THRESHOLD_MIN


class TestIsDirtyScaling:
    def test_neat_pet_dirty_at_lower_mess_level(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD_MIN)
        assert is_dirty(pet, tidiness=1.0) is True
        assert is_dirty(pet, tidiness=0.0) is False

    def test_messy_pet_tolerates_up_to_its_own_threshold(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD_MAX - 1)
        assert is_dirty(pet, tidiness=0.0) is False
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD_MAX)
        assert is_dirty(pet, tidiness=0.0) is True


class TestMessLabel:
    def test_zero_is_clean(self) -> None:
        pet = _pet(mess_level=0)
        assert mess_label(pet) == "clean"

    def test_below_threshold_is_a_little_messy(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD - 1)
        assert mess_label(pet) == "a little messy"

    def test_at_threshold_is_filthy(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD)
        assert mess_label(pet) == "filthy"

    def test_above_threshold_is_filthy(self) -> None:
        pet = _pet(mess_level=MESS_DIRTY_THRESHOLD + 5)
        assert mess_label(pet) == "filthy"


class TestCleanPet:
    def test_resets_mess_level_to_zero(self) -> None:
        pet = _pet(mess_level=5)
        clean_pet(pet, datetime.now(UTC))
        assert pet.mess_level == 0

    def test_sets_last_cleaned_at(self) -> None:
        pet = _pet(mess_level=2, last_cleaned_at=None)
        now = datetime.now(UTC)
        clean_pet(pet, now)
        assert pet.last_cleaned_at == now

    def test_returns_amount_cleared(self) -> None:
        pet = _pet(mess_level=7)
        cleared = clean_pet(pet, datetime.now(UTC))
        assert cleared == 7

    def test_cleaning_already_clean_pet_returns_zero(self) -> None:
        pet = _pet(mess_level=0)
        cleared = clean_pet(pet, datetime.now(UTC))
        assert cleared == 0
        assert pet.mess_level == 0
