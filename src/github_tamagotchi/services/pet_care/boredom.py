"""Boredom mood signal driven by how long it's been since the pet was played with.

Distinct from health/XP/evolution, which stay driven entirely by real repo
activity via `update_pet_from_repo` (see services/pet_logic.py) — this is a
mood/display layer only, exactly like the feed-vs-exercise mechanic in
services/pet_feeding.py. Boredom decays at a rate scaled by the pet's
`activity` personality trait: a more active pet gets bored faster (shorter
threshold), a lazy pet is content to sit around longer.
"""

from __future__ import annotations

from datetime import datetime

from github_tamagotchi.models.pet import Pet

BOREDOM_MAX_HOURS = 96  # activity=0.0 (lazy) — slowest to get bored
BOREDOM_MIN_HOURS = 12  # activity=1.0 (active) — fastest to get bored


def boredom_threshold_hours(activity: float) -> float:
    """Linear interpolation from BOREDOM_MAX_HOURS (lazy) to BOREDOM_MIN_HOURS (active).

    `activity` is clamped to [0.0, 1.0] before interpolating.
    """
    clamped = min(1.0, max(0.0, activity))
    return BOREDOM_MAX_HOURS + (BOREDOM_MIN_HOURS - BOREDOM_MAX_HOURS) * clamped


def is_bored(pet: Pet, activity: float, now: datetime) -> bool:
    """Whether the pet has gone too long without being played with.

    Reference point is `pet.last_played_at`, falling back to `pet.created_at`
    when the pet has never been played with yet — a fresh pet gets a grace
    period from hatching rather than starting out instantly bored.
    """
    reference = pet.last_played_at or pet.created_at
    compare_now = now.replace(tzinfo=None) if reference.tzinfo is None else now
    hours_since = (compare_now - reference).total_seconds() / 3600
    return hours_since > boredom_threshold_hours(activity)
