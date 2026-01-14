"""Main FastAPI application entry point."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from github_tamagotchi import __version__
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import async_session_factory, close_database
from github_tamagotchi.services import image_queue

# Set up paths for templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

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

    # Start image generation queue worker
    worker_stop_event = asyncio.Event()
    worker_task = asyncio.create_task(
        image_queue.run_worker(async_session_factory, worker_stop_event)
    )
    logger.info("Image generation queue worker started")

    yield

    # Shutdown
    # Stop image queue worker
    worker_stop_event.set()
    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task
    logger.info("Image generation queue worker stopped")

    scheduler.shutdown()
    await close_database()
    logger.info("GitHub Tamagotchi shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="A virtual pet that represents your GitHub repository's health",
    lifespan=lifespan,
)

app.include_router(router)

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """Landing page."""
    return templates.TemplateResponse("landing.html", {"request": request})
