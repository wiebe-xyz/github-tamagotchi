"""Tests for pet death mechanics."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.pet_logic import (
    ABANDONMENT_THRESHOLD_DAYS,
    DEATH_GRACE_PERIOD_DAYS,
    check_death_conditions,
    update_grace_period,
)


def _make_pet(**kwargs: Any) -> Any:
    """Create a minimal pet-like namespace for unit testing (no DB required)."""
    defaults: dict[str, Any] = {
        "repo_owner": "owner",
        "repo_name": "repo",
        "name": "TestPet",
        "stage": PetStage.EGG.value,
        "mood": PetMood.CONTENT.value,
        "health": 100,
        "experience": 0,
        "is_dead": False,
        "died_at": None,
        "cause_of_death": None,
        "grace_period_started": None,
        "last_fed_at": None,
        "last_checked_at": None,
        "created_at": datetime.now(UTC) - timedelta(days=10),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestUpdateGracePeriod:
    """Tests for update_grace_period."""

    def test_sets_grace_period_when_health_is_zero(self) -> None:
        now = datetime.now(UTC)
        pet = _make_pet(health=0, grace_period_started=None)
        update_grace_period(pet, now)
        assert pet.grace_period_started == now

    def test_does_not_overwrite_existing_grace_period(self) -> None:
        earlier = datetime.now(UTC) - timedelta(days=3)
        now = datetime.now(UTC)
        pet = _make_pet(health=0, grace_period_started=earlier)
        update_grace_period(pet, now)
        assert pet.grace_period_started == earlier

    def test_clears_grace_period_when_health_above_zero(self) -> None:
        earlier = datetime.now(UTC) - timedelta(days=2)
        pet = _make_pet(health=50, grace_period_started=earlier)
        update_grace_period(pet, datetime.now(UTC))
        assert pet.grace_period_started is None

    def test_does_nothing_when_health_above_zero_and_no_grace_period(self) -> None:
        pet = _make_pet(health=80, grace_period_started=None)
        update_grace_period(pet, datetime.now(UTC))
        assert pet.grace_period_started is None


class TestCheckDeathConditions:
    """Tests for check_death_conditions."""

    def test_no_death_for_healthy_active_pet(self) -> None:
        now = datetime.now(UTC)
        pet = _make_pet(
            health=80,
            grace_period_started=None,
            last_checked_at=now - timedelta(days=1),
            created_at=now - timedelta(days=30),
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is False
        assert cause is None

    def test_neglect_death_after_grace_period(self) -> None:
        now = datetime.now(UTC)
        pet = _make_pet(
            health=0,
            grace_period_started=now - timedelta(days=DEATH_GRACE_PERIOD_DAYS + 1),
            last_checked_at=now - timedelta(days=1),
            created_at=now - timedelta(days=30),
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is True
        assert cause == "neglect"

    def test_no_death_when_grace_period_not_elapsed(self) -> None:
        now = datetime.now(UTC)
        pet = _make_pet(
            health=0,
            grace_period_started=now - timedelta(days=DEATH_GRACE_PERIOD_DAYS - 1),
            last_checked_at=now - timedelta(days=1),
            created_at=now - timedelta(days=30),
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is False
        assert cause is None

    def test_abandonment_death_after_90_days_inactive(self) -> None:
        now = datetime.now(UTC)
        long_ago = now - timedelta(days=ABANDONMENT_THRESHOLD_DAYS + 1)
        pet = _make_pet(
            health=50,
            grace_period_started=None,
            last_checked_at=long_ago,
            created_at=long_ago - timedelta(days=10),
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is True
        assert cause == "abandonment"

    def test_no_abandonment_before_90_days(self) -> None:
        now = datetime.now(UTC)
        recent = now - timedelta(days=ABANDONMENT_THRESHOLD_DAYS - 1)
        pet = _make_pet(
            health=50,
            grace_period_started=None,
            last_checked_at=recent,
            created_at=now - timedelta(days=30),
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is False
        assert cause is None

    def test_abandonment_uses_last_fed_at_if_no_checked_at(self) -> None:
        now = datetime.now(UTC)
        long_ago = now - timedelta(days=ABANDONMENT_THRESHOLD_DAYS + 1)
        pet = _make_pet(
            health=50,
            grace_period_started=None,
            last_checked_at=None,
            last_fed_at=long_ago,
            created_at=long_ago - timedelta(days=10),
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is True
        assert cause == "abandonment"

    def test_abandonment_uses_created_at_as_fallback(self) -> None:
        now = datetime.now(UTC)
        long_ago = now - timedelta(days=ABANDONMENT_THRESHOLD_DAYS + 1)
        pet = _make_pet(
            health=50,
            grace_period_started=None,
            last_checked_at=None,
            last_fed_at=None,
            created_at=long_ago,
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is True
        assert cause == "abandonment"

    def test_abandonment_takes_priority_over_neglect(self) -> None:
        """Abandonment check runs first; if that triggers, cause is 'abandonment'."""
        now = datetime.now(UTC)
        long_ago = now - timedelta(days=ABANDONMENT_THRESHOLD_DAYS + 1)
        pet = _make_pet(
            health=0,
            grace_period_started=now - timedelta(days=DEATH_GRACE_PERIOD_DAYS + 1),
            last_checked_at=long_ago,
            created_at=long_ago - timedelta(days=10),
        )
        should_die, cause = check_death_conditions(pet, now)
        assert should_die is True
        assert cause == "abandonment"


class TestDeadPetBadge:
    """Tests for dead pet badge rendering."""

    def test_dead_badge_contains_grave_emoji(self) -> None:
        from github_tamagotchi.services.badge import generate_badge_svg

        svg = generate_badge_svg("Chompy", "adult", "happy", 80, is_dead=True)
        assert "🪦" in svg

    def test_dead_badge_contains_skull_emoji(self) -> None:
        from github_tamagotchi.services.badge import generate_badge_svg

        svg = generate_badge_svg("Chompy", "adult", "happy", 80, is_dead=True)
        assert "💀" in svg

    def test_dead_badge_contains_rip_label(self) -> None:
        from github_tamagotchi.services.badge import generate_badge_svg

        born = datetime(2024, 1, 1, tzinfo=UTC)
        died = datetime(2025, 6, 15, tzinfo=UTC)
        svg = generate_badge_svg(
            "Chompy", "adult", "happy", 80, is_dead=True, died_at=died, created_at=born
        )
        assert "RIP 2024–2025" in svg

    def test_dead_badge_contains_deceased_label(self) -> None:
        from github_tamagotchi.services.badge import generate_badge_svg

        svg = generate_badge_svg("Chompy", "adult", "happy", 80, is_dead=True)
        assert "Deceased" in svg

    def test_dead_badge_no_health_bar(self) -> None:
        from github_tamagotchi.services.badge import generate_badge_svg

        svg = generate_badge_svg("Chompy", "adult", "happy", 80, is_dead=True)
        # Health bar has specific "HP" label in live badge
        assert ">HP<" not in svg

    def test_dead_badge_uses_grey_accent(self) -> None:
        from github_tamagotchi.services.badge import generate_badge_svg

        svg = generate_badge_svg("Chompy", "adult", "happy", 80, is_dead=True)
        assert "#7f8c8d" in svg

    def test_live_badge_unchanged_when_not_dead(self) -> None:
        from github_tamagotchi.services.badge import generate_badge_svg

        svg = generate_badge_svg("Chompy", "adult", "happy", 80, is_dead=False)
        assert "🪦" not in svg
        assert "Deceased" not in svg
