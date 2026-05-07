"""Sprite sheet generation, frame extraction, and animated GIF composition."""

import base64
import io
import json
import re
from collections import deque
from dataclasses import dataclass, field

import httpx
import structlog
from opentelemetry.trace import SpanKind
from PIL import Image

from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.services.image_generation import (
    DEFAULT_STYLE,
    NEGATIVE_PROMPT,
    STYLES,
    get_pet_appearance,
)

logger = structlog.get_logger()
_tracer = get_tracer(__name__)

# Sprite sheet grid layout
SPRITE_COLS = 3
SPRITE_ROWS = 3

# Frame index constants — the canonical order we want
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
    (6, "eating", "mouth open, small food particle nearby, chewing expression"),
    (7, "excited", "wide eyes, jumping pose, exclamation sparkle"),
    (8, "angry", "furrowed brows, puffed cheeks, small angry vein mark"),
]

FRAME_NAMES = [name for _, name, _ in SPRITE_FRAMES]

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
        f"sprite sheet with EXACTLY {SPRITE_COLS} columns and {SPRITE_ROWS} rows "
        f"(a {SPRITE_COLS}x{SPRITE_ROWS} grid, {total_frames} equally-sized cells total). "
        f"Each cell must be the same width and height. "
        f"Solid flat magenta #FF00FF background filling the entire image. "
        f"Character: {character_desc}, {stage_desc}. "
        f"All {total_frames} cells show the EXACT SAME character with identical "
        f"proportions, identical colour palette, identical body shape. "
        f"Cells reading left-to-right then top-to-bottom: {frame_list}. "
        f"Do NOT label or number the cells. "
        f"Consistent style throughout, perfectly aligned grid, no extra rows or columns."
    )

    negative = (
        style_def.get("negative", NEGATIVE_PROMPT)
        + ", multiple different characters, text labels, numbers, digits, numerals, "
        "annotations, captions, extra rows, extra columns, "
        "uneven cells, misaligned grid, inconsistent character design, white background"
    )

    return prompt, negative


def _remove_background_from_corners(img: Image.Image, tolerance: int = 40) -> Image.Image:
    """Remove background by flood-filling inward from all border pixels.

    Collects distinct background colours from the four corner pixels, then
    seeds a BFS from every border pixel whose colour matches any corner
    colour within *tolerance*.  This handles frames where the character
    touches the edge and splits the background into disconnected regions.

    Args:
        img: RGBA PIL Image
        tolerance: Per-channel absolute tolerance for colour matching (default 40)

    Returns:
        RGBA image with connected background pixels made transparent
    """
    img = img.convert("RGBA")
    width, height = img.size
    pixels: list[tuple[int, ...]] = list(img.get_flattened_data())  # type: ignore[arg-type]

    corner_indices = [0, width - 1, (height - 1) * width, height * width - 1]
    bg_colors: list[tuple[int, int, int]] = []
    for ci in corner_indices:
        cr, cg, cb = pixels[ci][:3]
        if not any(
            abs(cr - er) <= tolerance and abs(cg - eg) <= tolerance and abs(cb - eb) <= tolerance
            for er, eg, eb in bg_colors
        ):
            bg_colors.append((cr, cg, cb))

    def _matches_any(r: int, g: int, b: int) -> bool:
        return any(
            abs(r - br) <= tolerance and abs(g - bg) <= tolerance and abs(b - bb) <= tolerance
            for br, bg, bb in bg_colors
        )

    result: list[tuple[int, ...]] = list(pixels)
    visited: list[bool] = [False] * (width * height)
    queue: deque[tuple[int, int]] = deque()

    for x in range(width):
        for y in (0, height - 1):
            idx = y * width + x
            if not visited[idx] and _matches_any(*pixels[idx][:3]):
                visited[idx] = True
                queue.append((x, y))
    for y in range(1, height - 1):
        for x in (0, width - 1):
            idx = y * width + x
            if not visited[idx] and _matches_any(*pixels[idx][:3]):
                visited[idx] = True
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        cidx = y * width + x
        r, g, b, a = result[cidx]
        result[cidx] = (r, g, b, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height:
                nidx = ny * width + nx
                if not visited[nidx]:
                    nr, ng, nb, _ = pixels[nidx]
                    if _matches_any(nr, ng, nb):
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
    with _tracer.start_as_current_span(
        "sprite.extract_frames",
        attributes={
            "sprite.cols": cols,
            "sprite.rows": rows,
        },
    ) as span:
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

        span.set_attribute("sprite.frame_count", len(frames))
        return frames


VISION_MODEL = "google/gemini-2.0-flash-001"
VISION_API_URL = "https://openrouter.ai/api/v1/chat/completions"


async def analyze_sprite_sheet(
    sprite_sheet_bytes: bytes,
    api_key: str,
) -> list[dict[str, str | int | bool]]:
    """Use a vision model to analyze a sprite sheet and identify each cell's content.

    Returns a list of dicts, one per grid cell (left-to-right, top-to-bottom):
        [{"index": 0, "empty": False, "emotion": "idle"}, ...]

    The emotion field is one of the FRAME_NAMES values, or "unknown".
    """
    from github_tamagotchi.services.openrouter import _set_genai_response_attributes

    with _tracer.start_as_current_span(
        f"chat {VISION_MODEL}",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": "openrouter",
            "gen_ai.request.model": VISION_MODEL,
            "server.address": "openrouter.ai",
            "server.port": 443,
        },
    ) as span:
        b64 = base64.b64encode(sprite_sheet_bytes).decode()
        data_uri = f"data:image/png;base64,{b64}"

        emotion_list = ", ".join(FRAME_NAMES)
        prompt = (
            "This is a pixel art sprite sheet arranged as a 3x3 grid (9 cells). "
            "Analyze each cell from left-to-right, top-to-bottom (cells 0-8). "
            "For each cell, determine:\n"
            "1. Whether it contains a character (not empty)\n"
            f"2. Which emotion best matches from: {emotion_list}\n\n"
            "Respond with ONLY a JSON array of 9 objects, no other text:\n"
            '[{"index": 0, "empty": false, "emotion": "idle"}, ...]\n'
            "If a cell is empty or has no character, set empty=true and emotion=\"unknown\"."
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(VISION_API_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

            _set_genai_response_attributes(span, data)

            text = data["choices"][0]["message"]["content"]
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                logger.warning("vision_analysis_no_json", response_text=text[:200])
                return []

            cells: list[dict[str, str | int | bool]] = json.loads(match.group())
            span.set_attribute("sprite.cell_count", len(cells))
            logger.info("vision_analysis_complete", cells=cells)
            return cells
        except Exception:
            span.set_attribute("error.type", "vision_analysis_error")
            logger.exception("vision_analysis_failed")
            return []


def reorder_frames_by_analysis(
    raw_frames: list[bytes],
    analysis: list[dict[str, str | int | bool]],
) -> list[bytes]:
    """Reorder extracted frames to match canonical FRAME_* order using vision analysis.

    Maps each analyzed cell to the canonical frame index by emotion name.
    Falls back to the first non-empty frame for any emotion not found.
    """
    with _tracer.start_as_current_span("sprite.reorder_frames"):
        if not analysis or len(raw_frames) != len(analysis):
            return raw_frames[:len(SPRITE_FRAMES)]

        emotion_to_frame_idx: dict[str, int] = {
            name: idx for idx, name, _ in SPRITE_FRAMES
        }

        available: dict[int, bytes] = {}
        first_nonempty: bytes | None = None

        for cell, frame_data in zip(analysis, raw_frames, strict=False):
            if cell.get("empty", False):
                continue
            if first_nonempty is None:
                first_nonempty = frame_data

            emotion = str(cell.get("emotion", "unknown")).lower()
            canonical_idx = emotion_to_frame_idx.get(emotion)
            if canonical_idx is not None and canonical_idx not in available:
                available[canonical_idx] = frame_data

        fallback = first_nonempty or raw_frames[0]
        ordered: list[bytes] = []
        for idx, _, _ in SPRITE_FRAMES:
            ordered.append(available.get(idx, fallback))

        return ordered


def _build_global_palette(
    rgba_images: list[Image.Image],
) -> Image.Image:
    """Build a shared 255-color palette from all frames combined."""
    widths = [img.width for img in rgba_images]
    total_w = sum(widths)
    h = rgba_images[0].height
    composite = Image.new("RGB", (total_w, h))
    x_off = 0
    for img in rgba_images:
        composite.paste(
            Image.merge("RGB", img.split()[:3]), (x_off, 0)
        )
        x_off += img.width
    return composite.quantize(
        colors=255, dither=Image.Dither.NONE
    )


def _apply_palette(
    img: Image.Image, palette_img: Image.Image,
) -> tuple[Image.Image, int]:
    """Map an RGBA image to a shared palette with transparency."""
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    p_img = rgb.quantize(
        palette=palette_img, dither=Image.Dither.NONE
    )

    palette = p_img.getpalette() or []
    while len(palette) < 256 * 3:
        palette.extend([255, 255, 255])
    palette[255 * 3: 255 * 3 + 3] = [255, 255, 255]
    p_img.putpalette(palette)

    alpha_bytes = a.tobytes()
    pixel_bytes = p_img.tobytes()
    new_pixels = [
        255 if alpha_bytes[i] < 128 else pixel_bytes[i]
        for i in range(len(pixel_bytes))
    ]
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
        health: Current pet health (0-100)

    Returns:
        Animated GIF bytes
    """
    with _tracer.start_as_current_span(
        "sprite.compose_animated_gif",
        attributes={
            "gif.mood": mood,
            "gif.health": health,
            "gif.frame_count": len(frames),
        },
    ) as span:
        if not frames:
            raise ValueError("No frames provided for GIF composition")

        effective_mood = (
            "sick"
            if health < 30 and mood not in ("sick",)
            else mood
        )
        sequence = MOOD_FRAME_SEQUENCE.get(
            effective_mood, IDLE_FRAME_SEQUENCE
        )

        max_idx = len(frames) - 1
        clamped_sequence = [min(i, max_idx) for i in sequence]

        rgba_images: list[Image.Image] = []
        for idx in clamped_sequence:
            raw = frames[idx]
            rgba_images.append(
                Image.open(io.BytesIO(raw)).convert("RGBA")
            )

        palette_img = _build_global_palette(rgba_images)

        pil_frames: list[Image.Image] = []
        durations: list[int] = []

        for img, idx in zip(rgba_images, clamped_sequence, strict=True):
            p_img, _ = _apply_palette(img, palette_img)
            pil_frames.append(p_img)
            durations.append(FRAME_DURATIONS.get(idx, 350))

        out = io.BytesIO()
        pil_frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=pil_frames[1:],
            loop=0,
            duration=durations,
            transparency=255,
            disposal=2,
        )
        gif_bytes = out.getvalue()
        span.set_attribute("gif.size_bytes", len(gif_bytes))
        return gif_bytes
