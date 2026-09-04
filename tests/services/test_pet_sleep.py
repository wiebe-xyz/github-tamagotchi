"""Tests for the time-of-day sleep mechanic."""

from datetime import UTC, datetime

from github_tamagotchi.services.pet_care.sleep import (
    SLEEP_END_HOUR_UTC,
    SLEEP_START_HOUR_UTC,
    is_asleep,
)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 4, hour, minute, tzinfo=UTC)


class TestIsAsleep:
    def test_late_evening_is_asleep(self) -> None:
        assert is_asleep(_at(23, 30)) is True

    def test_early_morning_is_asleep(self) -> None:
        assert is_asleep(_at(3, 0)) is True

    def test_midday_is_awake(self) -> None:
        assert is_asleep(_at(12, 0)) is False

    def test_start_hour_boundary_is_inclusive(self) -> None:
        assert is_asleep(_at(SLEEP_START_HOUR_UTC, 0)) is True
        assert is_asleep(_at(SLEEP_START_HOUR_UTC - 1, 59)) is False

    def test_end_hour_boundary_is_exclusive(self) -> None:
        assert is_asleep(_at(SLEEP_END_HOUR_UTC, 0)) is False
        assert is_asleep(_at(SLEEP_END_HOUR_UTC - 1, 59)) is True
