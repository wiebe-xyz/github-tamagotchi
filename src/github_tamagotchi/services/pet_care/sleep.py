"""Time-of-day sleep mechanic layered on top of the core health/XP system.

Health, XP, and evolution stay governed entirely by real repo activity (see
pet_logic.py) — that principle doesn't change. Sleep is a pure function of
wall-clock time: it has no persisted state and doesn't depend on the pet's
personality traits, unlike the other pet_care mechanics. The window wraps
midnight (22:00 UTC through 07:00 UTC the next day), so callers should not
assume the start hour is numerically less than the end hour.
"""

from __future__ import annotations

from datetime import datetime

SLEEP_START_HOUR_UTC = 22  # inclusive
SLEEP_END_HOUR_UTC = 7  # exclusive


def is_asleep(now: datetime) -> bool:
    """Whether the pet is asleep at the given time, by UTC hour.

    Asleep for the UTC hour range [SLEEP_START_HOUR_UTC, 24) union
    [0, SLEEP_END_HOUR_UTC) — i.e. 22:00 through 06:59, wrapping midnight.
    """
    hour = now.hour
    return hour >= SLEEP_START_HOUR_UTC or hour < SLEEP_END_HOUR_UTC
