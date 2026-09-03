"""Feed-vs-exercise mechanic layered on top of the core health/XP system.

Health, XP, and evolution stay governed entirely by real repo activity
(see pet_logic.py) — that principle doesn't change. Weight is a separate,
mostly-cosmetic stat: MCP's feed_pet tool can be called freely (unlike
health, it isn't gated on real signal), and overusing it has a real but
bounded cost — the pet gets chubby, then fat, and stops getting a health
bump from feeding until weight comes back down. update_pet_from_repo
(real activity) is what brings weight back down, so a pet that's actually
being worked on stays trim regardless of how often it's fed.
"""

from __future__ import annotations

from dataclasses import dataclass

from github_tamagotchi.models.pet import Pet, PetMood

FEED_WEIGHT_GAIN = 15.0
FEED_HEALTH_BOOST = 3
EXERCISE_WEIGHT_LOSS = 10.0
MIN_WEIGHT = 20.0
CHUBBY_THRESHOLD = 70.0
FAT_THRESHOLD = 100.0

# One-step-happier transitions for a "someone checked in" nudge. Deliberately
# capped at HAPPY, not DANCING — dancing is reserved for a real health win
# (see calculate_mood in pet_logic.py), not just being looked at.
_HAPPIER_STEP: dict[PetMood, PetMood] = {
    PetMood.SICK: PetMood.WORRIED,
    PetMood.LONELY: PetMood.CONTENT,
    PetMood.WORRIED: PetMood.CONTENT,
    PetMood.HUNGRY: PetMood.CONTENT,
    PetMood.CONTENT: PetMood.HAPPY,
    PetMood.HAPPY: PetMood.HAPPY,
    PetMood.DANCING: PetMood.DANCING,
}


def weight_label(weight: float) -> str:
    """Human-readable weight class, used in tool responses and ASCII art."""
    if weight >= FAT_THRESHOLD:
        return "fat"
    if weight >= CHUBBY_THRESHOLD:
        return "chubby"
    return "trim"


@dataclass
class FeedResult:
    weight_before: float
    weight_after: float
    health_change: int
    mood: str
    overfed: bool
    message: str


def apply_feed(pet: Pet) -> FeedResult:
    """Feed the pet. Mutates pet in place; caller commits.

    Raises weight unconditionally. Only raises health/mood if the pet
    wasn't already fat going in — feeding an already-fat pet doesn't help
    it, and nudges mood toward SICK instead of HAPPY as feedback that it's
    had enough.
    """
    weight_before = pet.weight
    was_already_fat = weight_before >= FAT_THRESHOLD

    pet.weight = weight_before + FEED_WEIGHT_GAIN

    if was_already_fat:
        health_change = 0
        pet.mood = PetMood.SICK.value
        message = (
            f"{pet.name} is already stuffed and doesn't want any more right now."
        )
    else:
        health_change = min(FEED_HEALTH_BOOST, 100 - pet.health)
        pet.health = min(100, pet.health + FEED_HEALTH_BOOST)
        pet.mood = _HAPPIER_STEP.get(PetMood(pet.mood), PetMood(pet.mood)).value
        message = f"{pet.name} happily eats up!"

    now_fat = pet.weight >= FAT_THRESHOLD
    if not was_already_fat and now_fat:
        message += f" ...and is now looking a little {weight_label(pet.weight)}."

    return FeedResult(
        weight_before=weight_before,
        weight_after=pet.weight,
        health_change=health_change,
        mood=pet.mood,
        overfed=was_already_fat,
        message=message,
    )


def apply_exercise_decay(pet: Pet) -> float:
    """Real activity burns off weight. Mutates pet in place; caller commits.

    Returns the amount of weight lost.
    """
    before = pet.weight
    pet.weight = max(MIN_WEIGHT, before - EXERCISE_WEIGHT_LOSS)
    return before - pet.weight


def nudge_mood_happier(pet: Pet) -> bool:
    """Move mood one step happier (capped at HAPPY). Returns True if changed."""
    current = PetMood(pet.mood)
    nxt = _HAPPIER_STEP.get(current, current)
    if nxt == current:
        return False
    pet.mood = nxt.value
    return True
