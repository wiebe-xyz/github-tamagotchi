"""Care mechanics: mess, boredom, neglect-hunger, and the sleep cycle.

A mood/display-only layer on top of the core health/XP/evolution system —
none of these mechanics touch health, XP, or evolution, which stay driven
entirely by real repo activity via `update_pet_from_repo` (see
services/pet_logic.py). Each mechanic lives in its own module below and
follows the same small-pure-function, mutate-pet-in-place, caller-commits
pattern established by services/pet_feeding.py. See
services/pet_logic.py:calculate_mood_with_care for how the four signals
combine into a single mood.
"""

from github_tamagotchi.services.pet_care.boredom import (
    BOREDOM_MAX_HOURS,
    BOREDOM_MIN_HOURS,
    boredom_threshold_hours,
    is_bored,
)
from github_tamagotchi.services.pet_care.mess import (
    MESS_DIRTY_THRESHOLD,
    MESS_PER_FEED,
    add_mess,
    clean_pet,
    is_dirty,
    mess_label,
)
from github_tamagotchi.services.pet_care.neglect_hunger import (
    NEGLECT_HUNGER_MAX_HOURS,
    NEGLECT_HUNGER_MIN_HOURS,
    is_neglected_hungry,
    neglect_hunger_threshold_hours,
)
from github_tamagotchi.services.pet_care.sleep import (
    SLEEP_END_HOUR_UTC,
    SLEEP_START_HOUR_UTC,
    is_asleep,
)

__all__ = [
    "BOREDOM_MAX_HOURS",
    "BOREDOM_MIN_HOURS",
    "MESS_DIRTY_THRESHOLD",
    "MESS_PER_FEED",
    "NEGLECT_HUNGER_MAX_HOURS",
    "NEGLECT_HUNGER_MIN_HOURS",
    "SLEEP_END_HOUR_UTC",
    "SLEEP_START_HOUR_UTC",
    "add_mess",
    "boredom_threshold_hours",
    "clean_pet",
    "is_asleep",
    "is_bored",
    "is_dirty",
    "is_neglected_hungry",
    "mess_label",
    "neglect_hunger_threshold_hours",
]
