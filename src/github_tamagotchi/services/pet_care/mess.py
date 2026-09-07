"""Mess mechanic: feeding leaves a mess, and it needs to be cleaned up.

Distinct from weight (services/pet_feeding.py) — mess is a separate cosmetic
signal driven by the same feed_pet action. Health, XP, and evolution stay
governed entirely by real repo activity (see pet_logic.py) — that principle
doesn't change here either. Mess only affects mood/display, via `is_dirty`
feeding into `calculate_mood_with_care`. The dirty threshold is scaled by
the pet's `tidiness` personality trait: a neat pet is bothered by mess much
sooner (lower threshold), a messy pet tolerates a lot more before it cares.
"""

from __future__ import annotations

from datetime import datetime

from github_tamagotchi.models.pet import Pet

MESS_PER_FEED = 1
MESS_DIRTY_THRESHOLD = 3  # fallback used by mess_label, and the tidiness=0.5 midpoint

MESS_DIRTY_THRESHOLD_MAX = 5  # tidiness=0.0 (messy) — tolerates the most mess
MESS_DIRTY_THRESHOLD_MIN = 1  # tidiness=1.0 (neat) — bothered almost immediately


def mess_dirty_threshold(tidiness: float) -> int:
    """Linear interpolation from MESS_DIRTY_THRESHOLD_MAX (messy) to
    MESS_DIRTY_THRESHOLD_MIN (neat), rounded to the nearest whole mess level.

    `tidiness` is clamped to [0.0, 1.0] before interpolating.
    """
    clamped = min(1.0, max(0.0, tidiness))
    raw = MESS_DIRTY_THRESHOLD_MAX + (MESS_DIRTY_THRESHOLD_MIN - MESS_DIRTY_THRESHOLD_MAX) * clamped
    return max(MESS_DIRTY_THRESHOLD_MIN, round(raw))


def add_mess(pet: Pet) -> None:
    """Feeding leaves a mess behind. Mutates pet in place; caller commits."""
    pet.mess_level += MESS_PER_FEED


def clean_pet(pet: Pet, now: datetime) -> int:
    """Clean up the pet's mess. Mutates pet in place; caller commits.

    Resets mess_level to 0 and records last_cleaned_at. Returns the mess
    level that was cleared.
    """
    cleared = pet.mess_level
    pet.mess_level = 0
    pet.last_cleaned_at = now
    return cleared


def is_dirty(pet: Pet, tidiness: float) -> bool:
    """Whether the pet's mess has crossed its (tidiness-scaled) dirty threshold."""
    return pet.mess_level >= mess_dirty_threshold(tidiness)


def mess_label(pet: Pet) -> str:
    """Human-readable mess class, used in tool responses and ASCII art.

    Uses the flat MESS_DIRTY_THRESHOLD rather than a per-pet tidiness scale —
    this is a display label describing the mess itself, not a mood judgment.
    """
    if pet.mess_level >= MESS_DIRTY_THRESHOLD:
        return "filthy"
    if pet.mess_level > 0:
        return "a little messy"
    return "clean"
