"""Pet naming utilities."""

import hashlib
import re

# Default pool of cute random names
CUTE_NAMES = [
    "Chippy",
    "Pixel",
    "Byte",
    "Sprout",
    "Biscuit",
    "Pebble",
    "Mochi",
    "Bubbles",
    "Coco",
    "Fizzle",
    "Noodle",
    "Pudding",
    "Ziggy",
    "Wobble",
    "Doodle",
    "Binky",
    "Pickle",
    "Squeak",
    "Toasty",
    "Waffles",
]

# Basic profanity list (extend as needed)
_PROFANITY = {
    "fuck",
    "shit",
    "ass",
    "bitch",
    "cunt",
    "damn",
    "hell",
    "bastard",
    "piss",
    "cock",
    "dick",
    "pussy",
    "whore",
    "slut",
    "nigger",
    "faggot",
}

# Pattern that allows only alphanumeric chars and spaces
_VALID_NAME_RE = re.compile(r"^[A-Za-z0-9 ]+$")


def generate_name_from_repo(repo_owner: str, repo_name: str) -> str:
    """Derive a cute default name from the repo name.

    Strategy:
    1. Split repo name on separators (hyphens, underscores, dots).
    2. Capitalise meaningful words and pick the best one.
    3. If nothing useful can be extracted, fall back to a deterministic
       random name from the CUTE_NAMES pool (seeded by the repo identity).
    """
    parts = re.split(r"[-_.]", repo_name)
    # Filter out generic noise words
    noise = {"my", "the", "a", "an", "of", "in", "to", "for", "is", "it"}
    candidates = [p.capitalize() for p in parts if p and p.lower() not in noise]

    if candidates:
        # Prefer the longest meaningful part (usually the most descriptive)
        name = max(candidates, key=len)
        # Append a cute suffix based on the last char to add personality
        last = name[-1].lower()
        name = name + "y" if last in "aeiou" else name + "ie"
        # Hard-cap at 20 chars
        return name[:20]

    # Fallback: deterministic pick from the cute names pool
    digest = hashlib.md5(f"{repo_owner}/{repo_name}".encode()).hexdigest()
    idx = int(digest, 16) % len(CUTE_NAMES)
    return CUTE_NAMES[idx]


def is_valid_pet_name(name: str) -> bool:
    """Return True if the name passes format and profanity checks."""
    if not name or len(name) > 20:
        return False
    if not _VALID_NAME_RE.match(name):
        return False
    lower = name.lower()
    return not any(bad in lower for bad in _PROFANITY)
