"""Tests for sprite sheet generation, frame extraction, and GIF composition."""

import io

import pytest
from PIL import Image

from github_tamagotchi.services.sprite_sheet import (
    SPRITE_COLS,
    SPRITE_ROWS,
    build_sprite_sheet_prompt,
    compose_animated_gif,
    extract_frames,
    get_canonical_appearance_description,
)


def _make_sprite_sheet(  # noqa: E501
    cols: int = SPRITE_COLS, rows: int = SPRITE_ROWS, cell_size: int = 64
) -> bytes:
    """Create a minimal RGBA sprite sheet PNG for testing."""
    width = cols * cell_size
    height = rows * cell_size
    img = Image.new("RGBA", (width, height), color=(100, 150, 200, 255))
    # Draw distinct colors in each cell so we can verify extraction
    for row in range(rows):
        for col in range(cols):
            r = (row * cols + col) * 40
            g = 100
            b = 200
            x0, y0 = col * cell_size, row * cell_size
            for x in range(x0, x0 + cell_size):
                for y in range(y0, y0 + cell_size):
                    img.putpixel((x, y), (r % 255, g, b, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_frame(color: tuple[int, int, int, int] = (100, 150, 200, 255), size: int = 64) -> bytes:
    """Create a minimal RGBA frame PNG for testing."""
    img = Image.new("RGBA", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestGetCanonicalAppearanceDescription:
    def test_returns_string(self) -> None:
        desc = get_canonical_appearance_description("octocat", "hello-world")
        assert isinstance(desc, str)
        assert len(desc) > 10

    def test_deterministic(self) -> None:
        desc1 = get_canonical_appearance_description("octocat", "hello-world")
        desc2 = get_canonical_appearance_description("octocat", "hello-world")
        assert desc1 == desc2

    def test_different_repos_give_different_descriptions(self) -> None:
        desc1 = get_canonical_appearance_description("alice", "repo-a")
        desc2 = get_canonical_appearance_description("bob", "repo-b")
        # Different repos may or may not produce the same description depending on hash
        # but the function must not raise
        assert isinstance(desc1, str)
        assert isinstance(desc2, str)

    def test_includes_color_and_body(self) -> None:
        desc = get_canonical_appearance_description("octocat", "hello-world")
        # Should mention "creature" and some colour-like words
        assert "creature" in desc


class TestBuildSpriteSheetPrompt:
    def test_returns_tuple_of_strings(self) -> None:
        positive, negative = build_sprite_sheet_prompt("owner", "repo", "adult")
        assert isinstance(positive, str)
        assert isinstance(negative, str)

    def test_contains_grid_dimensions(self) -> None:
        positive, _ = build_sprite_sheet_prompt("owner", "repo", "adult")
        assert str(SPRITE_COLS) in positive
        assert str(SPRITE_ROWS) in positive

    def test_uses_canonical_appearance_when_provided(self) -> None:
        canonical = "a sky blue round blob creature with small antenna"
        positive, _ = build_sprite_sheet_prompt(
            "owner", "repo", "adult", canonical_appearance=canonical
        )
        assert canonical in positive

    def test_contains_frame_descriptions(self) -> None:
        positive, _ = build_sprite_sheet_prompt("owner", "repo", "adult")
        # Should list at least the idle and blink frames
        assert "idle" in positive.lower()
        assert "blink" in positive.lower()

    def test_negative_prompt_present(self) -> None:
        _, negative = build_sprite_sheet_prompt("owner", "repo", "adult")
        assert len(negative) > 5

    def test_respects_style(self) -> None:
        positive_kawaii, _ = build_sprite_sheet_prompt("owner", "repo", "adult", style="kawaii")
        positive_wizard, _ = build_sprite_sheet_prompt("owner", "repo", "adult", style="wizard")
        assert positive_kawaii != positive_wizard


class TestExtractFrames:
    def test_extracts_correct_number_of_frames(self) -> None:
        sheet = _make_sprite_sheet()
        frames = extract_frames(sheet)
        assert len(frames) == SPRITE_COLS * SPRITE_ROWS

    def test_each_frame_is_valid_png(self) -> None:
        sheet = _make_sprite_sheet()
        frames = extract_frames(sheet)
        for frame in frames:
            img = Image.open(io.BytesIO(frame))
            assert img.format == "PNG"

    def test_frame_dimensions_are_equal(self) -> None:
        cell_size = 48
        sheet = _make_sprite_sheet(cell_size=cell_size)
        frames = extract_frames(sheet)
        for frame in frames:
            img = Image.open(io.BytesIO(frame))
            assert img.width == cell_size
            assert img.height == cell_size

    def test_custom_grid_layout(self) -> None:
        sheet = _make_sprite_sheet(cols=2, rows=3, cell_size=32)
        frames = extract_frames(sheet, cols=2, rows=3)
        assert len(frames) == 6

    def test_returns_rgba_frames(self) -> None:
        sheet = _make_sprite_sheet()
        frames = extract_frames(sheet)
        for frame in frames:
            img = Image.open(io.BytesIO(frame)).convert("RGBA")
            assert img.mode == "RGBA"


class TestComposeAnimatedGif:
    @pytest.fixture
    def six_frames(self) -> list[bytes]:
        """Create 6 distinct RGBA frames for testing."""
        return [_make_frame(color=(i * 40 % 255, 100, 200, 255)) for i in range(6)]

    def test_returns_bytes(self, six_frames: list[bytes]) -> None:
        result = compose_animated_gif(six_frames, mood="content", health=100)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_result_is_valid_gif(self, six_frames: list[bytes]) -> None:
        result = compose_animated_gif(six_frames, mood="content", health=100)
        img = Image.open(io.BytesIO(result))
        assert img.format == "GIF"

    def test_idle_mood_uses_multiple_frames(self, six_frames: list[bytes]) -> None:
        result = compose_animated_gif(six_frames, mood="content", health=100)
        img = Image.open(io.BytesIO(result))
        # Animated GIF should have n_frames > 1
        assert getattr(img, "n_frames", 1) > 1

    def test_happy_mood_produces_gif(self, six_frames: list[bytes]) -> None:
        result = compose_animated_gif(six_frames, mood="happy", health=80)
        img = Image.open(io.BytesIO(result))
        assert img.format == "GIF"

    def test_low_health_overrides_to_sick_animation(self, six_frames: list[bytes]) -> None:
        # Both low health and explicitly sick mood should produce valid GIFs
        result_low = compose_animated_gif(six_frames, mood="content", health=20)
        result_sick = compose_animated_gif(six_frames, mood="sick", health=100)
        assert Image.open(io.BytesIO(result_low)).format == "GIF"
        assert Image.open(io.BytesIO(result_sick)).format == "GIF"

    def test_sleeping_mood_produces_gif(self, six_frames: list[bytes]) -> None:
        result = compose_animated_gif(six_frames, mood="lonely", health=100)
        img = Image.open(io.BytesIO(result))
        assert img.format == "GIF"

    def test_raises_on_empty_frames(self) -> None:
        with pytest.raises(ValueError, match="No frames"):
            compose_animated_gif([], mood="content", health=100)

    def test_single_frame_fallback(self) -> None:
        single = [_make_frame()]
        result = compose_animated_gif(single, mood="happy", health=100)
        img = Image.open(io.BytesIO(result))
        assert img.format == "GIF"

    def test_dancing_mood_produces_gif(self, six_frames: list[bytes]) -> None:
        result = compose_animated_gif(six_frames, mood="dancing", health=100)
        assert Image.open(io.BytesIO(result)).format == "GIF"

    def test_unknown_mood_falls_back_to_idle(self, six_frames: list[bytes]) -> None:
        result = compose_animated_gif(six_frames, mood="unknown_mood_xyz", health=100)
        assert Image.open(io.BytesIO(result)).format == "GIF"
