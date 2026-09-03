"""Tests for ASCII rendering of a pet's appearance."""

import io
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.services.ascii_render import (
    _FALLBACK_ART,
    image_to_ascii,
    render_pet_ascii,
)
from github_tamagotchi.services.pet_feeding import CHUBBY_THRESHOLD, FAT_THRESHOLD


def _png_bytes(
    size: tuple[int, int] = (64, 64),
    color: tuple[int, int, int, int] = (10, 10, 10, 255),
) -> bytes:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    for y in range(size[1] // 4, size[1] * 3 // 4):
        for x in range(size[0] // 4, size[0] * 3 // 4):
            img.putpixel((x, y), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pet(**overrides: object) -> Pet:
    defaults: dict[str, object] = {
        "repo_owner": "o",
        "repo_name": "r",
        "name": "P",
        "stage": PetStage.BABY.value,
        "weight": 50.0,
    }
    defaults.update(overrides)
    return Pet(**defaults)  # type: ignore[arg-type]


class TestImageToAscii:
    def test_produces_non_empty_multiline_grid(self) -> None:
        art = image_to_ascii(_png_bytes())
        lines = art.split("\n")
        assert len(lines) > 1
        assert any(line.strip() for line in lines)

    def test_transparent_pixels_render_as_space(self) -> None:
        # A fully transparent image should render as all-blank rows.
        img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        art = image_to_ascii(buf.getvalue())
        assert art.strip() == ""

    def test_dark_region_maps_to_dense_characters(self) -> None:
        art = image_to_ascii(_png_bytes(color=(0, 0, 0, 255)))
        assert "@" in art or "#" in art


class TestFallbackArt:
    def test_every_stage_has_art(self) -> None:
        for stage in PetStage:
            assert stage in _FALLBACK_ART
            assert _FALLBACK_ART[stage].strip()

    async def test_no_storage_uses_fallback(self) -> None:
        pet = _pet(stage=PetStage.EGG.value)
        art = await render_pet_ascii(pet, None)
        assert art == _FALLBACK_ART[PetStage.EGG]

    async def test_fallback_notes_chubby_weight(self) -> None:
        pet = _pet(weight=CHUBBY_THRESHOLD)
        art = await render_pet_ascii(pet, None)
        assert "round" in art

    async def test_fallback_notes_fat_weight(self) -> None:
        pet = _pet(weight=FAT_THRESHOLD)
        art = await render_pet_ascii(pet, None)
        assert "overfed" in art

    async def test_storage_failure_falls_back_gracefully(self) -> None:
        pet = _pet(stage=PetStage.EGG.value)
        storage = MagicMock()
        storage.get_image = AsyncMock(side_effect=RuntimeError("boom"))
        art = await render_pet_ascii(pet, storage)
        assert art == _FALLBACK_ART[PetStage.EGG]

    async def test_no_image_yet_falls_back(self) -> None:
        pet = _pet(stage=PetStage.EGG.value)
        storage = MagicMock()
        storage.get_image = AsyncMock(return_value=None)
        art = await render_pet_ascii(pet, storage)
        assert art == _FALLBACK_ART[PetStage.EGG]


class TestRenderWithStorage:
    async def test_uses_real_image_when_available(self) -> None:
        pet = _pet(stage=PetStage.BABY.value)
        storage = MagicMock()
        storage.get_image = AsyncMock(return_value=_png_bytes())
        art = await render_pet_ascii(pet, storage)
        assert art != _FALLBACK_ART[PetStage.BABY]
        assert "\n" in art
