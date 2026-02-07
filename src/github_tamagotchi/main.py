"""Main FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from github_tamagotchi import __version__
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import async_session_factory, close_database
from github_tamagotchi.mcp.server import get_mcp_server
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.pet_logic import apply_repo_health_to_pet

# Set up paths for templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()


async def poll_repositories() -> None:
    """Periodic task to check all registered repositories."""
    logger.info("Starting repository health check poll")

    github = GitHubService()

    async with async_session_factory() as session:
        result = await session.execute(select(Pet))
        pets = result.scalars().all()

        for pet in pets:
            try:
                health = await github.get_repo_health(pet.repo_owner, pet.repo_name)
                changes = apply_repo_health_to_pet(pet, health)

                if changes["evolved"]:
                    logger.info(
                        "Pet evolved",
                        pet_name=pet.name,
                        repo=f"{pet.repo_owner}/{pet.repo_name}",
                        old_stage=changes["old_stage"],
                        new_stage=changes["new_stage"].value,
                    )

                logger.debug(
                    "Updated pet health",
                    pet_name=pet.name,
                    repo=f"{pet.repo_owner}/{pet.repo_name}",
                    health=pet.health,
                    mood=pet.mood,
                )
            except Exception:
                logger.exception(
                    "Failed to update pet",
                    pet_name=pet.name,
                    repo=f"{pet.repo_owner}/{pet.repo_name}",
                )

        await session.commit()

    logger.info("Repository health check complete", pets_updated=len(pets))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Startup
    logger.info("Starting GitHub Tamagotchi", version=__version__)

    # Start scheduler for periodic polling
    scheduler.add_job(
        poll_repositories,
        "interval",
        minutes=settings.github_poll_interval_minutes,
        id="poll_repositories",
    )
    scheduler.start()
    logger.info(
        "Scheduler started",
        poll_interval_minutes=settings.github_poll_interval_minutes,
    )

    yield

    # Shutdown
    scheduler.shutdown()
    await close_database()
    logger.info("GitHub Tamagotchi shutdown complete")


# Create the MCP server app
mcp_server = get_mcp_server()
mcp_app = mcp_server.http_app(path="")

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="A virtual pet that represents your GitHub repository's health",
    lifespan=lifespan,
)

app.include_router(router)

# Mount the MCP server at /mcp
app.mount("/mcp", mcp_app)

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """Landing page."""
    return templates.TemplateResponse(request, "landing.html")
