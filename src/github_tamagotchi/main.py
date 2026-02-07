"""Main FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.services.github import GitHubService, RateLimitError
from github_tamagotchi.services.pet_logic import (
    calculate_experience,
    calculate_health_delta,
    calculate_mood,
    get_next_stage,
)

# Set up paths for templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()


async def poll_repositories() -> None:
    """Periodic task to check all registered repositories."""
    logger.info("poll_started", message="Starting repository health check poll")

    github_service = GitHubService()
    updated_count = 0
    error_count = 0
    evolved_count = 0

    async with async_session_factory() as session:
        # Query all pets
        result = await session.execute(select(Pet))
        pets = result.scalars().all()

        logger.info("poll_pets_found", pet_count=len(pets))

        for pet in pets:
            try:
                # Fetch health metrics from GitHub
                health = await github_service.get_repo_health(pet.repo_owner, pet.repo_name)

                # Calculate state changes
                health_delta = calculate_health_delta(health)
                experience_gained = calculate_experience(health)
                new_health = max(0, min(100, pet.health + health_delta))
                new_experience = pet.experience + experience_gained
                new_mood = calculate_mood(health, new_health)

                # Check for evolution
                current_stage = PetStage(pet.stage)
                new_stage = get_next_stage(current_stage, new_experience)

                # Update pet
                pet.health = new_health
                pet.experience = new_experience
                pet.mood = new_mood.value
                pet.last_checked_at = datetime.now(UTC)

                # Handle evolution
                if new_stage != current_stage:
                    pet.stage = new_stage.value
                    evolved_count += 1
                    logger.info(
                        "pet_evolved",
                        pet_id=pet.id,
                        pet_name=pet.name,
                        repo=f"{pet.repo_owner}/{pet.repo_name}",
                        old_stage=current_stage.value,
                        new_stage=new_stage.value,
                        experience=new_experience,
                    )

                # Update last_fed_at if there was a recent commit
                if health.last_commit_at:
                    hours_since_commit = (
                        datetime.now(UTC) - health.last_commit_at
                    ).total_seconds() / 3600
                    if hours_since_commit < 24:
                        pet.last_fed_at = datetime.now(UTC)

                updated_count += 1

                logger.debug(
                    "pet_updated",
                    pet_id=pet.id,
                    pet_name=pet.name,
                    repo=f"{pet.repo_owner}/{pet.repo_name}",
                    health_delta=health_delta,
                    new_health=new_health,
                    experience_gained=experience_gained,
                    new_mood=new_mood.value,
                )

            except RateLimitError as e:
                logger.warning(
                    "poll_rate_limited",
                    pet_id=pet.id,
                    repo=f"{pet.repo_owner}/{pet.repo_name}",
                    reset_time=e.reset_time.isoformat() if e.reset_time else None,
                    message="GitHub API rate limit reached, stopping poll cycle",
                )
                # Stop polling to avoid hitting rate limits further
                break

            except Exception as e:
                error_count += 1
                logger.error(
                    "poll_pet_error",
                    pet_id=pet.id,
                    repo=f"{pet.repo_owner}/{pet.repo_name}",
                    error=str(e),
                )
                # Continue with other pets

        # Commit all changes
        await session.commit()

    logger.info(
        "poll_completed",
        updated_count=updated_count,
        error_count=error_count,
        evolved_count=evolved_count,
        message="Repository health check complete",
    )


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
mcp_app = mcp_server.http_app(path="/mcp")

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
    return templates.TemplateResponse("landing.html", {"request": request})
