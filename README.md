# GitHub Tamagotchi

A virtual pet that lives and dies by your GitHub repository's health. The creature evolves, develops a personality, and eventually dies if your project is neglected — all driven by real metrics.

## How It Works

Each repository gets a unique, deterministically generated pet. The same repo always produces the same creature: same colours, same body shape, same personality traits. From there, the pet's life is entirely driven by what happens in the repo.

**Health inputs** (calculated every 5 minutes):

| Signal | Effect |
|--------|--------|
| Commit in last 24h | +10 health |
| Successful CI run | +5 health |
| Release in last 30d | +2 per release (capped +10) |
| Active contributors | +1 per contributor (capped +8) |
| No commit in 3+ days | Pet gets hungry |
| PR open > 48h | Pet gets worried |
| Issue unanswered > 7d | Pet gets lonely |
| Stale dependencies | Pet gets sick |
| Security alerts | −2 to −20 per alert (×2 for high-dependency repos) |

**Evolution path**: Egg → Baby → Child → Teen → Adult → Elder (XP thresholds: 100 / 500 / 1500 / 5000 / 15000)

**Death**: Health at 0% for 7 consecutive days triggers death. No activity for 90 days triggers abandonment death. A memorial page replaces the pet profile. Resurrection is possible — the generation counter increments each time.

**Personality**: Five traits (activity, sociability, bravery, tidiness, appetite) are derived from the repo's SHA-256 hash and nudged by real health metrics over time. These influence status messages and flavour text.

## Features

- Animated GIF sprites — AI-generated, unique per pet, 6 evolution stages
- Unlockable skins: Classic (always), Robot (Adult+), Dragon (Elder), Ghost (recover from critical health 3×)
- Commit streak tracking (calendar-day based, capped to pet age)
- Dying banner with countdown when health reaches 0
- Team & org views — `/org/{org}` aggregates all pets, contributor standings, blame/heroes board
- Public leaderboard with opt-out
- Achievement system with milestone unlocks
- Embeddable SVG badges and showcase widgets
- Open Graph / Twitter Card meta tags for rich link previews
- Admin panel: pet gallery, job queue, webhook logs, achievement management, sprite regeneration

## Tech Stack

- **FastAPI** + **Jinja2** — API and server-rendered HTML
- **SQLAlchemy async** + **PostgreSQL** — pet state persistence
- **APScheduler** — periodic GitHub repository health checks
- **OpenRouter** (`google/gemini-2.5-flash-image`) — AI image generation
- **MinIO** — image and animated GIF storage
- **Prometheus** — metrics at `/metrics`
- **FastMCP** — MCP server for AI assistant integration

## Development

```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn github_tamagotchi.main:app --reload

# Run tests (1100+ tests, 75% coverage gate)
uv run pytest

# Lint + type-check
uv run ruff check .
uv run mypy .
```

## Configuration

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/tamagotchi
GITHUB_TOKEN=ghp_xxx
OPENROUTER_API_KEY=sk-or-xxx
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
ADMIN_GITHUB_LOGINS=your-github-username
```

## MCP Integration

The GitHub Tamagotchi exposes an MCP (Model Context Protocol) server that allows AI assistants to interact with your pets.

```json
{
  "mcpServers": {
    "github-tamagotchi": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp/mcp"
    }
  }
}
```

Available tools: `register_pet`, `check_pet_status`, `feed_pet`, `list_pets`, `get_pet_history`, `update_pet_from_repo`.

## Cost Reference

Images are generated once per pet per stage and cached. With 6 evolution stages, a single pet costs ~$0.18 in total image generation over its lifetime.

| Operation | Cost |
|-----------|------|
| Pet image generation (1024×1024 PNG) | ~$0.03 per image |

## Spec-Driven Development

This project uses [spec-kit](https://github.com/github/spec-kit) for spec-driven development. All significant features are specified before implementation — specs live in `specs/` and the project constitution is at `.specify/memory/constitution.md`.

The workflow:

```
/speckit-specify "feature description"   → write a spec
/speckit-plan                            → turn spec into technical plan
/speckit-tasks                           → break plan into tasks
/speckit-implement                       → execute
```

Retrospective specs covering everything built so far are in `specs/`:

| Spec | What it covers |
|------|----------------|
| `pet-lifecycle.md` | Evolution, health formula, mood system |
| `death-and-resurrection.md` | Grace period, abandonment, memorial, resurrection |
| `commit-streak.md` | Calendar-day tracking, age cap, dedup |
| `image-generation.md` | OpenRouter pipeline, sprite sheets, GIF composition |
| `authentication.md` | GitHub OAuth, JWT sessions, admin detection |
| `admin-system.md` | All `/admin/*` pages and permissions |
| `pet-personalization.md` | Personality, skins, naming, opt-outs |
| `social-and-engagement.md` | Leaderboard, achievements, badges, OG tags |
| `team-and-org.md` | Contributor dashboard, org overview, blame board |
| `monitoring.md` | Health checks, Prometheus metrics, alerting |

## Deployment

Deployed to a k3s cluster at `nijmegen.wiebe.xyz`. See `k8s/` for manifests.
