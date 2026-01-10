"""FastMCP server for GitHub Tamagotchi."""

from typing import Any

from fastmcp import FastMCP

from github_tamagotchi.services.github import GitHubService

mcp = FastMCP("GitHub Tamagotchi")


@mcp.tool()
async def check_pet_status(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Check the status of a pet for a GitHub repository.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Pet status including mood, health, and stage
    """
    # TODO: Integrate with database to get actual pet
    github = GitHubService()
    health = await github.get_repo_health(repo_owner, repo_name)

    return {
        "repo": f"{repo_owner}/{repo_name}",
        "health_metrics": {
            "last_commit": health.last_commit_at.isoformat() if health.last_commit_at else None,
            "open_prs": health.open_prs_count,
            "open_issues": health.open_issues_count,
            "ci_passing": health.last_ci_success,
        },
        "pet_status": "Pet integration pending - check repo health metrics above",
    }


@mcp.tool()
async def feed_pet(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Manually feed a pet (simulates activity).

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Updated pet status after feeding
    """
    # TODO: Implement actual feeding logic
    return {
        "repo": f"{repo_owner}/{repo_name}",
        "action": "feed",
        "result": "Pet feeding not yet implemented",
    }


@mcp.tool()
async def list_pets() -> dict[str, Any]:
    """List all registered pets.

    Returns:
        List of all pets and their current status
    """
    # TODO: Implement database query
    return {
        "pets": [],
        "message": "Pet listing not yet implemented",
    }


def get_mcp_server() -> FastMCP:
    """Get the MCP server instance."""
    return mcp
