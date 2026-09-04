"""Hunger-from-neglect: a second, independent hunger signal.

Distinct from the existing repo-inactivity hunger check in
`services/pet_logic.py` (`HUNGRY_THRESHOLD_DAYS`, based on `last_commit_at`)
— that one stays as-is and is untouched here. This mechanic instead tracks
whether the pet itself has been fed (`feed_pet` / `pet.last_fed_at`), scaled
by the pet's `appetite` personality trait: a pet with a high "hungry" trait
gets neglect-hungry faster than a light eater does.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from github_tamagotchi.models.pet import Pet

NEGLECT_HUNGER_MAX_HOURS = 120  # appetite=0.0 (light eater) — slowest to get hungry
NEGLECT_HUNGER_MIN_HOURS = 24  # appetite=1.0 (hungry trait) — fastest to get hungry


def neglect_hunger_threshold_hours(appetite: float) -> float:
    """Hours since last feeding before the pet is neglect-hungry.

    Linear interpolation between NEGLECT_HUNGER_MAX_HOURS (appetite=0.0) and
    NEGLECT_HUNGER_MIN_HOURS (appetite=1.0). appetite is clamped to [0, 1].
    """
    clamped = min(1.0, max(0.0, appetite))
    return NEGLECT_HUNGER_MAX_HOURS + clamped * (
        NEGLECT_HUNGER_MIN_HOURS - NEGLECT_HUNGER_MAX_HOURS
    )


def is_neglected_hungry(pet: Pet, appetite: float, now: datetime) -> bool:
    """Whether the pet has gone hungry from not being fed (fed_pet).

    Reference point is `pet.last_fed_at`, falling back to `pet.created_at`
    if never fed — a freshly hatched pet gets a grace period, not instant
    hunger.
    """
    reference = pet.last_fed_at or pet.created_at
    compare_now = now.replace(tzinfo=None) if reference.tzinfo is None else now
    hours_since = (compare_now - reference).total_seconds() / 3600
    return hours_since > neglect_hunger_threshold_hours(appetite)
