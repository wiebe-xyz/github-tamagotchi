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

## MCP Integration

The GitHub Tamagotchi exposes an MCP (Model Context Protocol) server that allows AI assistants to interact with your pets.

### Available MCP Tools

- **register_pet**: Create a new pet for a GitHub repository
- **check_pet_status**: Get current pet status and repository health metrics
- **feed_pet**: Manually feed a pet to increase health and happiness
- **list_pets**: List all registered pets
- **get_pet_history**: View pet evolution history and stats
- **update_pet_from_repo**: Sync pet status with current repository health

### Configuring MCP Client

Add the following to your MCP client configuration (e.g., `~/.claude/claude_code_config.json` for Claude Code):

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

For production deployments, replace `localhost:8000` with your deployment URL.

### MCP Endpoint

The MCP server is mounted at `/mcp/mcp` when running the application:

```bash
# Start the server
uv run uvicorn github_tamagotchi.main:app --reload

# MCP endpoint will be available at:
# http://localhost:8000/mcp/mcp
```

## Deployment

Deployed to k3s cluster at `nijmegen.wiebe.xyz`. See `k8s/` directory for manifests.
