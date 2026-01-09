# GitHub Tamagotchi

A virtual pet that represents your GitHub repository's health. The creature evolves and thrives based on real project metrics: commit frequency, PR merge times, issue response rates, and code quality indicators.

## Features

- **Pet Health System**: Your pet responds to repository activity
  - No commits in 3 days → Pet gets hungry
  - PR open > 48 hours → Pet looks worried
  - Issue unanswered > 1 week → Pet is lonely
  - Successful CI run → Pet does happy dance
  - Merge to main → Pet eats and grows
  - Stale dependencies → Pet gets sick

- **Evolution Path**: Egg → Baby → Child → Teen → Adult → Elder

- **MCP Integration**: Use FastMCP to interact with your pet from AI assistants

## Tech Stack

- **FastAPI**: REST API backend
- **FastMCP**: MCP server for AI assistant integration
- **PostgreSQL**: Pet state persistence
- **APScheduler**: Periodic GitHub repository health checks

## Development

```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn github_tamagotchi.main:app --reload

# Run tests
uv run pytest

# Run linting
uv run ruff check .
uv run mypy .
```

## Configuration

Set environment variables or create a `.env` file:

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/tamagotchi
GITHUB_TOKEN=ghp_xxx
```

## Deployment

Deployed to k3s cluster at `nijmegen.wiebe.xyz`. See `k8s/` directory for manifests.
