"""Mess mechanic: feeding leaves a mess, and it needs to be cleaned up.

Distinct from weight (services/pet_feeding.py) — mess is a separate cosmetic
signal driven by the same feed_pet action. Health, XP, and evolution stay
governed entirely by real repo activity (see pet_logic.py) — that principle
doesn't change here either. Mess only affects mood/display, via `is_dirty`
feeding into `calculate_mood_with_care`.
"""

from __future__ import annotations

from datetime import datetime

from github_tamagotchi.models.pet import Pet

MESS_PER_FEED = 1
MESS_DIRTY_THRESHOLD = 3


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


def is_dirty(pet: Pet) -> bool:
    """Whether the pet's mess has crossed the dirty threshold."""
    return pet.mess_level >= MESS_DIRTY_THRESHOLD


def mess_label(pet: Pet) -> str:
    """Human-readable mess class, used in tool responses and ASCII art."""
    if pet.mess_level >= MESS_DIRTY_THRESHOLD:
        return "filthy"
    if pet.mess_level > 0:
        return "a little messy"
    return "clean"
