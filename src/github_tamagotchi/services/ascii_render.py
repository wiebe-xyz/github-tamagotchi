"""Render a pet as ASCII art for MCP tool responses.

Preferred path: sample the pet's actual generated sprite (already unique
per repo — same deterministic-identity principle as everything else about
a pet) down to a small character grid by luminance. Falls back to a small
hand-drawn glyph per evolution stage when there's no generated image yet
(still an egg, image generation disabled, or the fetch simply fails) —
the tool should always return *something*, never a hard error over art.

Weight only visibly affects the fallback glyphs (hand-drawn, so a "chubby"
variant is just more text). It does not affect the real sampled sprite —
that's the separately-generated AI artwork, out of scope here.
"""

from __future__ import annotations

import io
from typing import cast

from PIL import Image

from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.services.pet_feeding import CHUBBY_THRESHOLD, FAT_THRESHOLD
from github_tamagotchi.services.storage import StorageService

# Dark-to-light ramp. Pet sprites render on a light/transparent background,
# so darker characters read as "ink" and get mapped to denser glyphs.
_RAMP = " .:-=+*#%@"


def image_to_ascii(image_bytes: bytes, width: int = 34) -> str:
    """Downsample a PNG to an ASCII grid by luminance.

    Transparent pixels are treated as background (space), not black, so a
    sprite on a transparent canvas doesn't render as a solid block.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # Character cells are roughly twice as tall as wide — halve the row
    # count relative to width so the result doesn't look squashed.
    aspect = img.height / img.width
    height = max(1, round(width * aspect * 0.5))
    img = img.resize((width, height))

    pixels = img.load()
    assert pixels is not None

    lines: list[str] = []
    for y in range(height):
        row_chars: list[str] = []
        for x in range(width):
            r, g, b, a = cast(tuple[int, int, int, int], pixels[x, y])
            if a < 32:
                row_chars.append(" ")
                continue
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            # Darker pixel -> denser character.
            idx = int((255 - luminance) / 255 * (len(_RAMP) - 1))
            row_chars.append(_RAMP[idx])
        lines.append("".join(row_chars).rstrip())
    return "\n".join(lines)


_FALLBACK_ART: dict[PetStage, str] = {
    PetStage.EGG: "   .--.\n  /    \\\n |  o o |\n  \\    /\n   '--'",
    PetStage.BABY: "  (\\_/)\n  ( •,•)\n  o(\")(\")",
    PetStage.CHILD: "   /\\_/\\\n  ( o.o )\n   > ^ <\n  /|   |\\",
    PetStage.TEEN: "   /\\_/\\____\n  ( o.o )   \\\n   > ^ <  ~  )\n  /|     |\\_/",
    PetStage.ADULT: "    /\\___/\\\n   (  o.o  )\n    >  ^  <\n   /|     |\\\n    |     |",
    PetStage.ELDER: "   .~~~~~.\n  ( ^   ^ )\n   >  ~  <\n  /|     |\\\n / |     | \\",
}

_CHUBBY_SUFFIX = "\n  (looking a bit round!)"
_FAT_SUFFIX = "\n  (definitely overfed!)"


def _fallback_art(stage: PetStage, weight: float) -> str:
    art = _FALLBACK_ART.get(stage, _FALLBACK_ART[PetStage.EGG])
    if weight >= FAT_THRESHOLD:
        return art + _FAT_SUFFIX
    if weight >= CHUBBY_THRESHOLD:
        return art + _CHUBBY_SUFFIX
    return art


async def render_pet_ascii(pet: Pet, storage: StorageService | None) -> str:
    """Best-effort ASCII rendering of a pet's current appearance."""
    if storage is not None:
        try:
            image_bytes = await storage.get_image(pet.repo_owner, pet.repo_name, pet.stage)
            if image_bytes:
                return image_to_ascii(image_bytes)
        except Exception:
            pass  # fall through to the hand-drawn fallback below

    return _fallback_art(PetStage(pet.stage), pet.weight)
