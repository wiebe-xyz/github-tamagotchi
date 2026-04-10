"""SVG badge generation for pet state visualization."""

import math
from datetime import datetime
from enum import StrEnum
from typing import Any

from github_tamagotchi.models.pet import PetMood, PetStage

STAGE_EMOJI: dict[str, str] = {
    PetStage.EGG: "🥚",
    PetStage.BABY: "🐣",
    PetStage.CHILD: "🐥",
    PetStage.TEEN: "🐦",
    PetStage.ADULT: "🦉",
    PetStage.ELDER: "🦅",
}

MOOD_EMOJI: dict[str, str] = {
    PetMood.HAPPY: "😊",
    PetMood.CONTENT: "😌",
    PetMood.HUNGRY: "😤",
    PetMood.WORRIED: "😰",
    PetMood.LONELY: "😢",
    PetMood.SICK: "🤒",
    PetMood.DANCING: "💃",
}

MOOD_COLOR: dict[str, str] = {
    PetMood.HAPPY: "#2ecc71",
    PetMood.CONTENT: "#3498db",
    PetMood.HUNGRY: "#e67e22",
    PetMood.WORRIED: "#f39c12",
    PetMood.LONELY: "#9b59b6",
    PetMood.SICK: "#e74c3c",
    PetMood.DANCING: "#1abc9c",
}

# (animation-name, timing) per mood
MOOD_ANIMATION: dict[str, tuple[str, str]] = {
    PetMood.HAPPY: ("bounce", "1s ease-in-out infinite"),
    PetMood.DANCING: ("bounce", "0.6s ease-in-out infinite"),
    PetMood.CONTENT: ("float", "3s ease-in-out infinite"),
    PetMood.HUNGRY: ("shake", "0.5s ease-in-out infinite"),
    PetMood.WORRIED: ("shake", "0.8s ease-in-out infinite"),
    PetMood.LONELY: ("pulse", "2s ease-in-out infinite"),
    PetMood.SICK: ("pulse", "1.5s ease-in-out infinite"),
}

_KEYFRAMES = (
    "@keyframes bounce{"
    "0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}"
    "@keyframes float{"
    "0%,100%{transform:translateY(0) rotate(-1deg)}"
    "50%{transform:translateY(-2px) rotate(1deg)}}"
    "@keyframes shake{"
    "0%,100%{transform:translateX(0)}"
    "25%{transform:translateX(-2px)}75%{transform:translateX(2px)}}"
    "@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}"
)

BADGE_STYLES = {"playful", "minimal", "maintained"}
DEFAULT_BADGE_STYLE = "playful"

_CENTER = 'text-anchor="middle" dominant-baseline="middle"'
_START = 'text-anchor="start" dominant-baseline="middle"'
_END = 'text-anchor="end" dominant-baseline="middle"'

# Layout constants for sprite badge (160px wide)
_SPRITE_W = 160
_SPRITE_X = 4       # sprite image x offset
_SPRITE_Y = 9       # sprite image y offset
_SPRITE_SIZE = 56   # sprite image width and height
_TEXT_X = 66        # x start of right-side text column
_TEXT_RIGHT = 156   # x end of right-side text (for right-aligned elements)


def _health_color(health: int) -> str:
    if health >= 70:
        return "#2ecc71"
    if health >= 40:
        return "#f39c12"
    return "#e74c3c"


def _sprite_image_element(b64: str, anim_name: str | None, anim_timing: str | None) -> list[str]:
    """Build SVG elements for an embedded sprite image with optional animation."""
    img_elem = (
        f'  <image x="{_SPRITE_X}" y="{_SPRITE_Y}" width="{_SPRITE_SIZE}" height="{_SPRITE_SIZE}"'
        f' href="data:image/png;base64,{b64}"/>'
    )
    if anim_name:
        cx = _SPRITE_X + _SPRITE_SIZE // 2
        cy = _SPRITE_Y + _SPRITE_SIZE // 2
        return [
            f'  <g style="animation:{anim_name} {anim_timing};transform-origin:{cx}px {cy}px">',
            f"  {img_elem.strip()}",
            "  </g>",
        ]
    return [img_elem]


def _playful_badge(
    display_name: str,
    stage: str,
    mood: str,
    health: int,
    *,
    commit_streak: int = 0,
    pet_image_b64: str | None = None,
) -> str:
    """Dark gradient badge with emoji sprites (original style)."""
    stage_sprite = STAGE_EMOJI.get(stage, "🥚")
    mood_sprite = MOOD_EMOJI.get(mood, "😌")
    accent = MOOD_COLOR.get(mood, "#3498db")
    hp_color = _health_color(health)
    health_pct = max(0, min(100, health))
    stage_label = stage.capitalize()
    mood_label = mood.capitalize()

    has_sprite = bool(pet_image_b64)
    width = _SPRITE_W if has_sprite else 120

    if has_sprite:
        # 160px wide layout with sprite image
        # HP bar: x=76 to x=148 → 72px max
        health_bar_width = round(health_pct * 0.72)

        anim_pair = MOOD_ANIMATION.get(mood)
        anim_name = anim_pair[0] if anim_pair else None
        anim_timing = anim_pair[1] if anim_pair else None

        defs_lines: list[str] = [
            "  <defs>",
            f"    <style>{_KEYFRAMES}</style>",
            '    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">',
            '      <stop offset="0" stop-color="#1a1a2e"/>',
            '      <stop offset="1" stop-color="#16213e"/>',
            "    </linearGradient>",
            '    <clipPath id="r">',
            f'      <rect width="{width}" height="80" rx="6"/>',
            "    </clipPath>",
            "  </defs>",
        ]

        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="80"'
            f' role="img" aria-label="Pet: {display_name}">',
            f"  <title>{display_name} ({stage_label})</title>",
            *defs_lines,
            f'  <rect width="{width}" height="80" rx="6" fill="url(#bg)"/>',
            f'  <rect width="{width}" height="3" fill="{accent}"/>',
        ]

        assert pet_image_b64 is not None
        lines.extend(_sprite_image_element(pet_image_b64, anim_name, anim_timing))

        lines += [
            f'  <text x="{_TEXT_X}" y="22" font-size="10" fill="#ecf0f1" {_START}'
            f' font-family="monospace">{display_name}</text>',
            f'  <text x="{_TEXT_X}" y="35" font-size="8" fill="{accent}" {_START}'
            f' font-family="sans-serif">{mood_label}</text>',
            f'  <text x="{_TEXT_X}" y="48" font-size="8" fill="#bdc3c7" {_START}'
            f' font-family="sans-serif">{stage_label}</text>',
            f'  <text x="{_TEXT_X}" y="69" font-size="7" fill="#7f8c8d" {_START}'
            f' font-family="sans-serif">HP</text>',
            '  <rect x="76" y="65" width="73" height="5" rx="2" fill="#2c3e50"/>',
            f'  <rect x="76" y="65" width="{health_bar_width}" height="5"'
            f' rx="2" fill="{hp_color}"/>',
            f'  <text x="{_TEXT_RIGHT}" y="69" font-size="7" fill="{hp_color}" {_END}'
            f' font-family="monospace">{health_pct}</text>',
        ]

        if commit_streak >= 7:
            lines.append(
                f'  <text x="{_TEXT_RIGHT}" y="14" font-size="7" fill="#ff9800" {_END}'
                f' font-family="monospace">🔥{commit_streak}</text>'
            )
    else:
        # 120px wide layout with emoji (original)
        health_bar_width = round(health_pct * 0.65)  # 65px max bar width

        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"'
            f' role="img" aria-label="Pet: {display_name}">',
            f"  <title>{display_name} ({stage_label})</title>",
            "  <defs>",
            '    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">',
            '      <stop offset="0" stop-color="#1a1a2e"/>',
            '      <stop offset="1" stop-color="#16213e"/>',
            "    </linearGradient>",
            '    <clipPath id="r">',
            '      <rect width="120" height="80" rx="6"/>',
            "    </clipPath>",
            "  </defs>",
            '  <rect width="120" height="80" rx="6" fill="url(#bg)"/>',
            f'  <rect width="120" height="3" fill="{accent}"/>',
            f'  <text x="18" y="44" font-size="28" {_CENTER}>{stage_sprite}</text>',
            f'  <text x="38" y="30" font-size="12" {_START}>{mood_sprite}</text>',
            f'  <text x="38" y="44" font-size="10" fill="#ecf0f1" {_START}'
            f' font-family="monospace">{display_name}</text>',
            f'  <text x="38" y="57" font-size="8" fill="#bdc3c7" {_START}'
            f' font-family="sans-serif">{stage_label}</text>',
            f'  <text x="16" y="71" font-size="7" fill="#7f8c8d" {_START}'
            f' font-family="sans-serif">HP</text>',
            '  <rect x="26" y="67" width="80" height="5" rx="2" fill="#2c3e50"/>',
            f'  <rect x="26" y="67" width="{health_bar_width}" height="5"'
            f' rx="2" fill="{hp_color}"/>',
            f'  <text x="109" y="71" font-size="7" fill="{hp_color}" {_END}'
            f' font-family="monospace">{health_pct}</text>',
        ]

        if commit_streak >= 7:
            lines.append(
                f'  <text x="116" y="14" font-size="7" fill="#ff9800" {_END}'
                f' font-family="monospace">🔥{commit_streak}</text>'
            )

    lines.append("</svg>")
    return "\n".join(lines)


def _minimal_badge(
    display_name: str,
    stage: str,
    mood: str,
    health: int,
    *,
    commit_streak: int = 0,
) -> str:
    """Clean, text-only badge with minimal decoration."""
    hp_color = _health_color(health)
    health_pct = max(0, min(100, health))
    stage_label = stage.capitalize()
    mood_label = mood.capitalize()

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"'
        f' role="img" aria-label="Pet: {display_name}">',
        f"  <title>{display_name} ({stage_label})</title>",
        '  <rect width="120" height="60" rx="4" fill="#f8f9fa"/>',
        '  <rect width="120" height="2" rx="1" fill="#dee2e6"/>',
        '  <rect x="0" y="58" width="120" height="2" rx="1" fill="#dee2e6"/>',
        f'  <text x="8" y="20" font-size="10" fill="#212529" {_START}'
        f' font-family="monospace" font-weight="bold">{display_name}</text>',
        f'  <text x="8" y="35" font-size="8" fill="#6c757d" {_START}'
        f' font-family="sans-serif">{stage_label} · {mood_label}</text>',
        f'  <text x="8" y="49" font-size="7" fill="#adb5bd" {_START}'
        f' font-family="sans-serif">HP</text>',
        '  <rect x="22" y="44" width="86" height="4" rx="2" fill="#e9ecef"/>',
        f'  <rect x="22" y="44" width="{round(health_pct * 0.86)}" height="4"'
        f' rx="2" fill="{hp_color}"/>',
    ]

    if commit_streak >= 7:
        lines.append(
            f'  <text x="112" y="20" font-size="7" fill="#fd7e14" {_END}'
            f' font-family="sans-serif">🔥{commit_streak}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


def _maintained_badge(display_name: str, stage: str, health: int) -> str:
    """Shields.io-style "maintained" badge."""
    health_pct = max(0, min(100, health))

    if health_pct >= 70:
        status_text = "healthy"
        status_color = "#2ecc71"
    elif health_pct >= 40:
        status_text = "struggling"
        status_color = "#f39c12"
    else:
        status_text = "critical"
        status_color = "#e74c3c"

    stage_label = stage.capitalize()
    label_w = 68
    value_w = 52
    total_w = label_w + value_w
    label_x = label_w // 2
    value_x = label_w + value_w // 2

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20"'
        f' role="img" aria-label="{display_name}: {status_text}">',
        f"  <title>{display_name} ({stage_label}) – {status_text}</title>",
        "  <defs>",
        '    <linearGradient id="s" x2="0" y2="100%">',
        '      <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>',
        '      <stop offset="1" stop-opacity=".1"/>',
        "    </linearGradient>",
        f'    <clipPath id="r"><rect width="{total_w}" height="20" rx="3"/></clipPath>',
        "  </defs>",
        '  <g clip-path="url(#r)">',
        f'    <rect width="{label_w}" height="20" fill="#555"/>',
        f'    <rect x="{label_w}" width="{value_w}" height="20" fill="{status_color}"/>',
        f'    <rect width="{total_w}" height="20" fill="url(#s)"/>',
        "  </g>",
        f'  <text x="{label_x}" y="14" font-size="9" fill="#fff" text-anchor="middle"'
        f' font-family="DejaVu Sans,Verdana,Geneva,sans-serif">{display_name}</text>',
        f'  <text x="{value_x}" y="14" font-size="9" fill="#fff" text-anchor="middle"'
        f' font-family="DejaVu Sans,Verdana,Geneva,sans-serif">{status_text}</text>',
        "</svg>",
    ]
    return "\n".join(lines)


def _dead_badge(
    display_name: str,
    *,
    died_at: datetime | None = None,
    created_at: datetime | None = None,
    badge_style: str = DEFAULT_BADGE_STYLE,
    pet_image_b64: str | None = None,
) -> str:
    """Badge for a deceased pet (all styles share same deceased rendering)."""
    born_year = created_at.year if created_at else "?"
    died_year = died_at.year if died_at else "?"
    rip_label = f"RIP {born_year}–{died_year}"

    if badge_style == "maintained":
        label_w = 68
        value_w = 52
        total_w = label_w + value_w
        label_x = label_w // 2
        value_x = label_w + value_w // 2
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="20"'
            f' role="img" aria-label="{display_name}: deceased">',
            f"  <title>{display_name} (Deceased)</title>",
            "  <defs>",
            f'    <clipPath id="r"><rect width="{total_w}" height="20" rx="3"/></clipPath>',
            "  </defs>",
            '  <g clip-path="url(#r)">',
            f'    <rect width="{label_w}" height="20" fill="#555"/>',
            f'    <rect x="{label_w}" width="{value_w}" height="20" fill="#7f8c8d"/>',
            "  </g>",
            f'  <text x="{label_x}" y="14" font-size="9" fill="#fff" text-anchor="middle"'
            f' font-family="DejaVu Sans,Verdana,Geneva,sans-serif">{display_name}</text>',
            f'  <text x="{value_x}" y="14" font-size="9" fill="#fff" text-anchor="middle"'
            f' font-family="DejaVu Sans,Verdana,Geneva,sans-serif">deceased</text>',
            "</svg>",
        ]
        return "\n".join(lines)

    if badge_style == "minimal":
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"'
            f' role="img" aria-label="Pet: {display_name} (Deceased)">',
            f"  <title>{display_name} (Deceased)</title>",
            '  <rect width="120" height="60" rx="4" fill="#f8f9fa"/>',
            '  <rect width="120" height="2" rx="1" fill="#dee2e6"/>',
            '  <rect x="0" y="58" width="120" height="2" rx="1" fill="#dee2e6"/>',
            f'  <text x="8" y="20" font-size="10" fill="#495057" {_START}'
            f' font-family="monospace" font-weight="bold">{display_name}</text>',
            f'  <text x="8" y="35" font-size="8" fill="#adb5bd" {_START}'
            f' font-family="sans-serif">Deceased</text>',
            f'  <text x="8" y="50" font-size="7" fill="#ced4da" {_START}'
            f' font-family="sans-serif">{rip_label}</text>',
            "</svg>",
        ]
        return "\n".join(lines)

    # playful (default) — supports sprite with greyscale filter
    accent = "#7f8c8d"
    has_sprite = bool(pet_image_b64)
    width = _SPRITE_W if has_sprite else 120

    defs_inner: list[str] = [
        '    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">',
        '      <stop offset="0" stop-color="#1a1a1a"/>',
        '      <stop offset="1" stop-color="#2c2c2c"/>',
        "    </linearGradient>",
    ]
    if has_sprite:
        defs_inner.append(
            '    <filter id="gs">'
            '<feColorMatrix type="saturate" values="0"/>'
            "</filter>"
        )

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="80"'
        f' role="img" aria-label="Pet: {display_name} (Deceased)">',
        f"  <title>{display_name} (Deceased)</title>",
        "  <defs>",
        *defs_inner,
        "  </defs>",
        f'  <rect width="{width}" height="80" rx="6" fill="url(#bg)"/>',
        f'  <rect width="{width}" height="3" fill="{accent}"/>',
    ]

    if has_sprite:
        assert pet_image_b64 is not None
        lines.append(
            f'  <image x="{_SPRITE_X}" y="{_SPRITE_Y}" width="{_SPRITE_SIZE}"'
            f' height="{_SPRITE_SIZE}" href="data:image/png;base64,{pet_image_b64}"'
            f' filter="url(#gs)"/>'
        )
        tx = _TEXT_X
        tcenter = _TEXT_RIGHT
    else:
        lines.append(f'  <text x="18" y="44" font-size="28" {_CENTER}>🪦</text>')
        lines.append(f'  <text x="38" y="30" font-size="12" {_START}>💀</text>')
        tx = 38
        tcenter = 60

    lines += [
        f'  <text x="{tx}" y="30" font-size="10" fill="#9e9e9e" {_START}'
        f' font-family="monospace">{display_name}</text>',
        f'  <text x="{tx}" y="44" font-size="8" fill="#7f8c8d" {_START}'
        f' font-family="sans-serif">Deceased</text>',
        f'  <text x="{tcenter}" y="60" font-size="7" fill="#7f8c8d" {_CENTER}'
        f' font-family="sans-serif">{rip_label}</text>',
        "</svg>",
    ]
    return "\n".join(lines)


def generate_badge_svg(
    name: str,
    stage: str,
    mood: str,
    health: int,
    *,
    is_dead: bool = False,
    died_at: datetime | None = None,
    created_at: datetime | None = None,
    commit_streak: int = 0,
    pet_image_b64: str | None = None,
    badge_style: str = DEFAULT_BADGE_STYLE,
) -> str:
    """Generate an SVG badge representing the current pet state.

    Args:
        name: Pet name.
        stage: Pet stage string.
        mood: Pet mood string.
        health: Pet health (0–100).
        is_dead: Whether the pet is deceased.
        died_at: Datetime the pet died (for RIP label).
        created_at: Datetime the pet was created (for RIP label).
        commit_streak: Current commit streak count.
        pet_image_b64: Base64-encoded PNG sprite, or None to use emoji fallback.
        badge_style: Visual style — "playful", "minimal", or "maintained".
    """
    display_name = name if len(name) <= 14 else name[:13] + "…"

    if is_dead:
        return _dead_badge(
            display_name,
            died_at=died_at,
            created_at=created_at,
            badge_style=badge_style,
            pet_image_b64=pet_image_b64,
        )

    if badge_style == "minimal":
        return _minimal_badge(
            display_name, stage, mood, health, commit_streak=commit_streak
        )

    if badge_style == "maintained":
        return _maintained_badge(display_name, stage, health)

    # Default: playful
    return _playful_badge(
        display_name, stage, mood, health, commit_streak=commit_streak, pet_image_b64=pet_image_b64
    )


class ContributorStanding(StrEnum):
    """A contributor's current standing with the pet."""

    FAVORITE = "favorite"
    GOOD = "good"
    NEUTRAL = "neutral"
    DOGHOUSE = "doghouse"
    ABSENT = "absent"


# Visual config per standing
_STANDING_CONFIG: dict[str, dict[str, str]] = {
    ContributorStanding.FAVORITE: {
        "accent": "#f1c40f",
        "icon": "💕",
        "label": "Favorite Human",
        "verb": "loves",
    },
    ContributorStanding.GOOD: {
        "accent": "#2ecc71",
        "icon": "✨",
        "label": "Good Standing",
        "verb": "appreciates",
    },
    ContributorStanding.NEUTRAL: {
        "accent": "#3498db",
        "icon": "",
        "label": "Contributor",
        "verb": "knows",
    },
    ContributorStanding.DOGHOUSE: {
        "accent": "#e74c3c",
        "icon": "💩",
        "label": "Doghouse",
        "verb": "is disappointed in",
    },
    ContributorStanding.ABSENT: {
        "accent": "#9b59b6",
        "icon": "😢",
        "label": "Missing",
        "verb": "misses",
    },
}


def generate_contributor_badge_svg(
    pet_name: str,
    pet_stage: str,
    username: str,
    standing: str,
    *,
    score: int | None = None,
    days_away: int | None = None,
    shame_detail: str | None = None,
) -> str:
    """Generate an SVG contributor badge showing a user's standing with the pet.

    Args:
        pet_name: Name of the pet.
        pet_stage: Current stage of the pet (for emoji selection).
        username: GitHub username of the contributor.
        standing: One of the ContributorStanding values.
        score: Point score to display (used for GOOD standing).
        days_away: Days since last commit (used for ABSENT standing).
        shame_detail: Short explanation for DOGHOUSE (shown when details=true).
    """
    cfg = _STANDING_CONFIG.get(standing, _STANDING_CONFIG[ContributorStanding.NEUTRAL])
    accent: str = cfg["accent"]
    icon: str = cfg["icon"]
    label: str = cfg["label"]
    verb: str = cfg["verb"]

    stage_emoji = STAGE_EMOJI.get(pet_stage, "🐣")

    # Truncate strings to keep badge compact
    display_pet = pet_name if len(pet_name) <= 12 else pet_name[:11] + "…"
    display_user = username if len(username) <= 14 else username[:13] + "…"

    width = 200
    height = 56

    # Build detail line text
    if standing == ContributorStanding.FAVORITE:
        detail = "⭐ Favorite Human"
    elif standing == ContributorStanding.GOOD and score is not None:
        detail = f"{score} pts"
    elif standing == ContributorStanding.ABSENT and days_away is not None:
        detail = f"{days_away}d away"
    elif standing == ContributorStanding.DOGHOUSE and shame_detail:
        detail = shame_detail
    elif standing == ContributorStanding.DOGHOUSE:
        detail = "Fix your PR!"
    else:
        detail = ""

    icon_part = f"{icon} " if icon else ""
    main_text = f"{stage_emoji}{icon_part}{display_pet} {verb} {display_user}"
    # Truncate main text if too long for the badge
    if len(main_text) > 32:
        main_text = main_text[:31] + "…"

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' role="img" aria-label="{display_pet}\'s opinion of {display_user}">',
        f"  <title>{display_pet}'s opinion of {display_user} ({label})</title>",
        "  <defs>",
        '    <linearGradient id="cbg" x1="0" y1="0" x2="0" y2="1">',
        '      <stop offset="0" stop-color="#1a1a2e"/>',
        '      <stop offset="1" stop-color="#16213e"/>',
        "    </linearGradient>",
        '    <clipPath id="cr">',
        f'      <rect width="{width}" height="{height}" rx="6"/>',
        "    </clipPath>",
        "  </defs>",
        f'  <rect width="{width}" height="{height}" rx="6" fill="url(#cbg)"/>',
        f'  <rect width="{width}" height="3" fill="{accent}"/>',
        f'  <text x="10" y="24" font-size="11" fill="#ecf0f1"'
        f' font-family="monospace" dominant-baseline="middle">{main_text}</text>',
    ]

    if detail:
        lines.append(
            f'  <text x="10" y="43" font-size="9" fill="{accent}"'
            f' font-family="sans-serif" dominant-baseline="middle">{detail}</text>'
        )

    lines.append("</svg>")
    return "\n".join(lines)


# ── Showcase widget ──────────────────────────────────────────────────────────

_CARD_W = 90
_CARD_H = 72
_CARD_GAP = 6
_CARD_PAD = 8

# Theme configs: (card_bg, outer_bg, text_color, sub_color)
_THEME: dict[str, tuple[str, str, str, str]] = {
    "dark": ("#1a1a2e", "#16213e", "#ecf0f1", "#bdc3c7"),
    "light": ("#f8f9fa", "#e9ecef", "#212529", "#6c757d"),
}


def _showcase_card(
    pet: dict[str, Any],
    x: int,
    y: int,
    card_bg: str,
    text_color: str,
) -> list[str]:
    """Build SVG elements for a single pet card in the showcase."""
    raw_name = pet["name"]
    name = raw_name[:10] + "…" if len(raw_name) > 10 else raw_name
    stage = pet.get("stage", "egg")
    mood = pet.get("mood", "content")
    is_dead = pet.get("is_dead", False)

    stage_emoji = STAGE_EMOJI.get(stage, "🥚")
    mood_color = MOOD_COLOR.get(mood, "#3498db")

    accent = "#7f8c8d" if is_dead else mood_color
    emoji = "🪦" if is_dead else stage_emoji

    cx = x + _CARD_W // 2

    return [
        f'  <rect x="{x}" y="{y}" width="{_CARD_W}" height="{_CARD_H}" rx="6" fill="{card_bg}"/>',
        f'  <rect x="{x}" y="{y}" width="{_CARD_W}" height="3" rx="1" fill="{accent}"/>',
        f'  <text x="{cx}" y="{y + 30}" font-size="22"'
        f' text-anchor="middle" dominant-baseline="middle">{emoji}</text>',
        f'  <text x="{cx}" y="{y + 50}" font-size="8" fill="{text_color}"'
        f' text-anchor="middle" dominant-baseline="middle" font-family="monospace">{name}</text>',
        f'  <circle cx="{cx}" cy="{y + 64}" r="4" fill="{accent}" opacity="0.8"/>',
    ]


def _showcase_positions(n: int, layout: str) -> tuple[list[tuple[int, int]], int, int]:
    """Compute (x, y) card positions and total (width, height) for a given layout."""
    if layout == "vertical":
        cols, rows = 1, n
    elif layout == "grid":
        cols = min(n, 3)
        rows = math.ceil(n / cols)
    else:  # horizontal
        cols, rows = n, 1

    total_w = _CARD_PAD + cols * (_CARD_W + _CARD_GAP) - _CARD_GAP + _CARD_PAD
    total_h = _CARD_PAD + rows * (_CARD_H + _CARD_GAP) - _CARD_GAP + _CARD_PAD

    positions: list[tuple[int, int]] = []
    for i in range(n):
        col = i % cols
        row = i // cols
        px = _CARD_PAD + col * (_CARD_W + _CARD_GAP)
        py = _CARD_PAD + row * (_CARD_H + _CARD_GAP)
        positions.append((px, py))

    return positions, total_w, total_h


def generate_showcase_svg(
    pets: list[dict[str, Any]],
    username: str,
    *,
    layout: str = "horizontal",
    theme: str = "dark",
) -> str:
    """Generate an SVG showcase of all pets for a GitHub user.

    Args:
        pets: List of pet dicts with keys: name, stage, mood, health, is_dead.
        username: GitHub username shown in the title.
        layout: Card arrangement — "horizontal", "vertical", or "grid".
        theme: Colour scheme — "dark" or "light".
    """
    card_bg, outer_bg, text_color, sub_color = _THEME.get(theme, _THEME["dark"])

    if not pets:
        width, height = 220, 44
        return "\n".join([
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
            f' role="img" aria-label="No pets for {username}">',
            f"  <title>{username} has no pets yet</title>",
            f'  <rect width="{width}" height="{height}" rx="6" fill="{outer_bg}"/>',
            f'  <text x="{width // 2}" y="{height // 2}" font-size="10"'
            f' fill="{sub_color}" text-anchor="middle" dominant-baseline="middle"'
            f' font-family="sans-serif">No pets yet for @{username}</text>',
            "</svg>",
        ])

    positions, total_w, total_h = _showcase_positions(len(pets), layout)
    pet_word = "pets" if len(pets) != 1 else "pet"

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}"'
        f' role="img" aria-label="Pets for @{username}">',
        f"  <title>@{username}'s pets ({len(pets)} {pet_word})</title>",
        f'  <rect width="{total_w}" height="{total_h}" rx="8" fill="{outer_bg}"/>',
    ]

    for pet, (px, py) in zip(pets, positions, strict=True):
        lines.extend(_showcase_card(pet, px, py, card_bg, text_color))

    lines.append("</svg>")
    return "\n".join(lines)
