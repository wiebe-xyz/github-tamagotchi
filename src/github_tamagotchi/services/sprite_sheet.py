"""Sprite sheet generation, frame extraction, and animated GIF composition."""

import io
from collections import deque
from dataclasses import dataclass, field

import structlog
from PIL import Image

from github_tamagotchi.services.image_generation import (
    DEFAULT_STYLE,
    NEGATIVE_PROMPT,
    STYLES,
    get_pet_appearance,
)

logger = structlog.get_logger()

# Sprite sheet grid layout
SPRITE_COLS = 3
SPRITE_ROWS = 2

# Frame index constants
FRAME_IDLE = 0
FRAME_BLINK = 1
FRAME_HAPPY = 2
FRAME_SAD = 3
FRAME_SICK = 4
FRAME_SLEEPING = 5

# Frame definitions: (index, name, prompt description)
SPRITE_FRAMES: list[tuple[int, str, str]] = [
    (FRAME_IDLE, "idle", "idle neutral pose, upright, neutral expression, eyes open"),
    (FRAME_BLINK, "blink", "same pose as frame 1, eyes fully closed in a blink, tiny smile"),
    (FRAME_HAPPY, "happy", "happy expression, big smile, small sparkles, slight bounce"),
    (FRAME_SAD, "sad", "sad frown, single teardrop on cheek, slightly slumped posture"),
    (FRAME_SICK, "sick", "sickly green tinge, droopy half-closed eyes, unsteady outline"),
    (FRAME_SLEEPING, "sleeping", "eyes closed, small zzz bubble floating above, resting"),
]

# Frame display durations in milliseconds
FRAME_DURATIONS: dict[int, int] = {
    FRAME_IDLE: 400,
    FRAME_BLINK: 180,
    FRAME_HAPPY: 350,
    FRAME_SAD: 500,
    FRAME_SICK: 500,
    FRAME_SLEEPING: 700,
}

# Mood to animation frame sequence mapping
MOOD_FRAME_SEQUENCE: dict[str, list[int]] = {
    "happy": [FRAME_HAPPY, FRAME_IDLE, FRAME_HAPPY, FRAME_IDLE],
    "dancing": [FRAME_HAPPY, FRAME_IDLE, FRAME_HAPPY, FRAME_IDLE],
    "content": [FRAME_IDLE, FRAME_BLINK, FRAME_IDLE],
    "hungry": [FRAME_IDLE, FRAME_BLINK, FRAME_IDLE],
    "worried": [FRAME_IDLE, FRAME_BLINK, FRAME_IDLE],
    "lonely": [FRAME_SLEEPING, FRAME_SAD, FRAME_SLEEPING],
    "sick": [FRAME_SICK, FRAME_IDLE, FRAME_SICK],
}
IDLE_FRAME_SEQUENCE = [FRAME_IDLE, FRAME_BLINK, FRAME_IDLE]


@dataclass
class SpriteSheetResult:
    """Result of sprite sheet generation."""

    success: bool
    sprite_sheet_data: bytes | None = None
    frames: list[bytes] = field(default_factory=list)
    canonical_appearance: str | None = None
    error: str | None = None


def get_canonical_appearance_description(owner: str, repo: str) -> str:
    """Generate a canonical appearance description string for a pet.

    This description is stored once and reused across sprite sheet generations
    to preserve character consistency.
    """
    appearance = get_pet_appearance(owner, repo)
    return (
        f"a {appearance.color} and {appearance.accent_color} "
        f"{appearance.body_type} creature with {appearance.feature}"
    )


def build_sprite_sheet_prompt(
    owner: str,
    repo: str,
    stage: str,
    style: str = DEFAULT_STYLE,
    canonical_appearance: str | None = None,
) -> tuple[str, str]:
    """Build prompt and negative prompt for sprite sheet generation.

    Args:
        owner: Repository owner
        repo: Repository name
        stage: Pet evolution stage
        style: Visual style key
        canonical_appearance: Previously stored appearance description (for consistency)

    Returns:
        Tuple of (positive_prompt, negative_prompt)
    """
    from github_tamagotchi.models.pet import PetStage
    from github_tamagotchi.services.image_generation import STAGE_PROMPTS

    style_def = STYLES.get(style, STYLES[DEFAULT_STYLE])
    stage_desc = STAGE_PROMPTS.get(stage, STAGE_PROMPTS[PetStage.ADULT.value])

    character_desc = canonical_appearance or get_canonical_appearance_description(owner, repo)

    frame_list = ", ".join(
        f"[{i + 1}] {desc}" for i, (_, _, desc) in enumerate(SPRITE_FRAMES)
    )

    total_frames = SPRITE_COLS * SPRITE_ROWS
    prompt = (
        f"{style_def['prompt_prefix']} "
        f"sprite sheet, {SPRITE_COLS} columns by {SPRITE_ROWS} rows grid, "
        f"thin white separator lines between cells, "
        f"transparent or solid flat magenta background #FF00FF. "
        f"Character: {character_desc}, {stage_desc}. "
        f"All {total_frames} frames show the EXACT SAME character with identical "
        f"proportions, identical colour palette, identical body shape. "
        f"Frames reading left to right then top to bottom: {frame_list}. "
        f"Consistent style throughout, clean cell alignment."
    )

    negative = (
        style_def.get("negative", NEGATIVE_PROMPT)
        + ", multiple different characters, text labels, cut off frames, "
        "misaligned grid, inconsistent character design"
    )

    return prompt, negative


def _remove_background_from_corners(img: Image.Image, tolerance: int = 40) -> Image.Image:
    """Remove background by flood-filling outward from all four corners.

    Samples the top-left corner pixel as the background colour reference, then
    BFS-floods from all 4 corners making matched pixels transparent.  This
    works regardless of the exact shade the AI model generates (hot-pink,
    magenta, salmon, etc.) and will never remove interior pixels of the same
    colour because they are not reachable from the border.

    Args:
        img: RGBA PIL Image
        tolerance: Per-channel absolute tolerance for colour matching (default 40)

    Returns:
        RGBA image with connected background pixels made transparent
    """
    img = img.convert("RGBA")
    width, height = img.size
    pixels = list(img.getdata())

    # Derive background colour from the top-left corner pixel
    bg_r, bg_g, bg_b = pixels[0][:3]

    def _matches(r: int, g: int, b: int) -> bool:
        return bool(
            abs(r - bg_r) <= tolerance
            and abs(g - bg_g) <= tolerance
            and abs(b - bg_b) <= tolerance
        )

    result: list[tuple[int, int, int, int]] = list(pixels)
    visited: list[bool] = [False] * (width * height)

    queue: deque[tuple[int, int]] = deque()
    for sx, sy in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        idx = sy * width + sx
        if not visited[idx]:
            r, g, b, _ = pixels[idx]
            if _matches(r, g, b):
                visited[idx] = True
                queue.append((sx, sy))

    while queue:
        x, y = queue.popleft()
        idx = y * width + x
        r, g, b, a = result[idx]
        result[idx] = (r, g, b, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height:
                nidx = ny * width + nx
                if not visited[nidx]:
                    nr, ng, nb, _ = pixels[nidx]
                    if _matches(nr, ng, nb):
                        visited[nidx] = True
                        queue.append((nx, ny))

    out = img.copy()
    out.putdata(result)
    return out


def extract_frames(
    sprite_sheet_bytes: bytes,
    cols: int = SPRITE_COLS,
    rows: int = SPRITE_ROWS,
    border_trim: int = 2,
) -> list[bytes]:
    """Extract individual frames from a sprite sheet.

    Slices the sprite sheet grid into individual frame images using equal-width
    columns and equal-height rows. Removes magenta chroma-key background and
    trims separator-line borders.

    Args:
        sprite_sheet_bytes: Raw sprite sheet image bytes (PNG)
        cols: Number of columns in the grid
        rows: Number of rows in the grid
        border_trim: Pixels to trim from each edge to remove cell separator lines

    Returns:
        List of PNG frame bytes in reading order (left-to-right, top-to-bottom)
    """
    img = Image.open(io.BytesIO(sprite_sheet_bytes)).convert("RGBA")
    width, height = img.size
    frame_w = width // cols
    frame_h = height // rows

    frames: list[bytes] = []
    for row in range(rows):
        for col in range(cols):
            x = col * frame_w
            y = row * frame_h
            frame = img.crop((x, y, x + frame_w, y + frame_h))
            # Trim separator borders
            if border_trim > 0:
                fw, fh = frame.size
                frame = frame.crop((
                    border_trim,
                    border_trim,
                    fw - border_trim,
                    fh - border_trim,
                ))
            # Remove background by flood-filling from corners
            frame = _remove_background_from_corners(frame)
            out = io.BytesIO()
            frame.save(out, format="PNG")
            frames.append(out.getvalue())

    return frames


def _rgba_to_gif_frame(img: Image.Image) -> tuple[Image.Image, int]:
    """Convert an RGBA image to a GIF-compatible palette image with transparency.

    Args:
        img: RGBA PIL Image

    Returns:
        Tuple of (P-mode palette image, transparency index)
    """
    # Ensure RGBA
    img = img.convert("RGBA")
    r, g, b, a = img.split()

    # Quantize the RGB data to 255 colors (leaving index 255 for transparency)
    rgb_img = Image.merge("RGB", (r, g, b))
    p_img = rgb_img.quantize(colors=255, dither=Image.Dither.NONE)

    # Extend palette to 256 entries with white at index 255 (the transparent slot)
    palette = p_img.getpalette() or []
    # Ensure palette has 256 * 3 entries
    while len(palette) < 256 * 3:
        palette.extend([255, 255, 255])
    palette[255 * 3 : 255 * 3 + 3] = [255, 255, 255]
    p_img.putpalette(palette)

    # Replace fully transparent pixels with the transparency index
    alpha_bytes = a.tobytes()
    pixel_bytes = p_img.tobytes()
    new_pixels = [255 if alpha_bytes[i] < 128 else pixel_bytes[i] for i in range(len(pixel_bytes))]
    p_img.putdata(new_pixels)

    return p_img, 255


def compose_animated_gif(
    frames: list[bytes],
    mood: str = "content",
    health: int = 100,
) -> bytes:
    """Compose an animated GIF from extracted sprite sheet frames.

    Selects the animation frame sequence based on current mood and health.

    Args:
        frames: List of PNG frame bytes (from extract_frames)
        mood: Current pet mood string
        health: Current pet health (0-100); health < 30 overrides to sick animation

    Returns:
        Animated GIF bytes
    """
    if not frames:
        raise ValueError("No frames provided for GIF composition")

    # Override to sick animation when health is very low
    effective_mood = "sick" if health < 30 and mood not in ("sick",) else mood

    sequence = MOOD_FRAME_SEQUENCE.get(effective_mood, IDLE_FRAME_SEQUENCE)

    # Clamp indices to available frames
    max_idx = len(frames) - 1
    clamped_sequence = [min(i, max_idx) for i in sequence]

    pil_frames: list[Image.Image] = []
    durations: list[int] = []
    transparency_indices: list[int] = []

    for idx in clamped_sequence:
        raw = frames[idx]
        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        p_img, trans_idx = _rgba_to_gif_frame(img)
        pil_frames.append(p_img)
        durations.append(FRAME_DURATIONS.get(idx, 350))
        transparency_indices.append(trans_idx)

    out = io.BytesIO()
    pil_frames[0].save(
        out,
        format="GIF",
        save_all=True,
        append_images=pil_frames[1:],
        loop=0,
        duration=durations,
        transparency=transparency_indices[0],
        disposal=2,
    )
    return out.getvalue()
