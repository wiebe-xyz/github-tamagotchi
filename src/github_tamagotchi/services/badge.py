"""SVG badge generation for pet state visualization."""

from datetime import datetime

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

_CENTER = 'text-anchor="middle" dominant-baseline="middle"'
_START = 'text-anchor="start" dominant-baseline="middle"'
_END = 'text-anchor="end" dominant-baseline="middle"'


def _health_color(health: int) -> str:
    if health >= 70:
        return "#2ecc71"
    if health >= 40:
        return "#f39c12"
    return "#e74c3c"


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
) -> str:
    """Generate an SVG badge representing the current pet state."""
    # Truncate name to keep badge width manageable
    display_name = name if len(name) <= 14 else name[:13] + "…"

    if is_dead:
        stage_sprite = "🪦"
        mood_sprite = "💀"
        accent = "#7f8c8d"
        born_year = created_at.year if created_at else "?"
        died_year = died_at.year if died_at else "?"
        rip_label = f"RIP {born_year}–{died_year}"
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"'
            f' role="img" aria-label="Pet: {display_name} (Deceased)">',
            f"  <title>{display_name} (Deceased)</title>",
            "  <defs>",
            '    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">',
            '      <stop offset="0" stop-color="#1a1a1a"/>',
            '      <stop offset="1" stop-color="#2c2c2c"/>',
            "    </linearGradient>",
            "  </defs>",
            '  <rect width="120" height="80" rx="6" fill="url(#bg)"/>',
            f'  <rect width="120" height="3" fill="{accent}"/>',
            f'  <text x="18" y="44" font-size="28" {_CENTER}>{stage_sprite}</text>',
            f'  <text x="38" y="30" font-size="12" {_START}>{mood_sprite}</text>',
            f'  <text x="38" y="44" font-size="10" fill="#9e9e9e" {_START}'
            f' font-family="monospace">{display_name}</text>',
            f'  <text x="38" y="57" font-size="8" fill="#7f8c8d" {_START}'
            f' font-family="sans-serif">Deceased</text>',
            f'  <text x="60" y="71" font-size="7" fill="#7f8c8d" {_CENTER}'
            f' font-family="sans-serif">{rip_label}</text>',
            "</svg>",
        ]
        return "\n".join(lines)

    stage_sprite = STAGE_EMOJI.get(stage, "🥚")
    mood_sprite = MOOD_EMOJI.get(mood, "😌")
    accent = MOOD_COLOR.get(mood, "#3498db")
    hp_color = _health_color(health)
    health_pct = max(0, min(100, health))
    health_bar_width = round(health_pct * 0.65)  # 65px max bar width

    stage_label = stage.capitalize()

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
        f'  <rect x="26" y="67" width="{health_bar_width}" height="5" rx="2" fill="{hp_color}"/>',
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
