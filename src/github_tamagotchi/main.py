"""Main FastAPI application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
import structlog

from github_tamagotchi import __version__
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.config import settings

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()


async def poll_repositories() -> None:
    """Periodic task to check all registered repositories."""
    logger.info("Starting repository health check poll")
    # TODO: Query database for all pets and update their health
    logger.info("Repository health check complete")


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
    logger.info("GitHub Tamagotchi shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="A virtual pet that represents your GitHub repository's health",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
    }
