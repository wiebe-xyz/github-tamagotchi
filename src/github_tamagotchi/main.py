"""Main FastAPI application entry point."""

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import sentry_sdk
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi import __version__
from github_tamagotchi.api.alerts import alert_router
from github_tamagotchi.api.auth import auth_router, get_admin_user, get_optional_user
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import async_session_factory, close_database, get_session
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.mcp.server import get_mcp_server
from github_tamagotchi.models.job_run import JobRun
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.models.webhook_event import WebhookEvent
from github_tamagotchi.services import image_queue
from github_tamagotchi.services.alerting import AlertChecker
from github_tamagotchi.services.github import GitHubService, RateLimitError
from github_tamagotchi.services.pet_logic import (
    EVOLUTION_THRESHOLDS,
    calculate_experience,
    calculate_health_delta,
    calculate_mood,
    check_death_conditions,
    get_next_stage,
    update_commit_streak,
    update_grace_period,
)

# Set up paths for templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()

# Track consecutive poll failures for alerting
_consecutive_poll_failures = 0


async def poll_repositories(triggered_by: str = "scheduler") -> None:
    """Periodic task to check all registered repositories."""
    global _consecutive_poll_failures  # noqa: PLW0603

    logger.info(
        "poll_started",
        message="Starting repository health check poll",
        triggered_by=triggered_by,
    )

    github_service = GitHubService()
    updated_count = 0
    error_count = 0
    evolved_count = 0
    rate_limited = False
    error_messages: list[str] = []

    async with async_session_factory() as session:
        # Create a JobRun record
        job_run = JobRun(
            job_name="poll_repositories",
            status="running",
            triggered_by=triggered_by,
        )
        session.add(job_run)
        await session.flush()  # get job_run.id
        job_run_id = job_run.id
        await session.commit()

    try:
        async with async_session_factory() as session:
            # Query all pets
            result = await session.execute(select(Pet))
            pets = result.scalars().all()
            total_pets = len(pets)

            logger.info("poll_pets_found", pet_count=total_pets)

            for pet in pets:
                try:
                    now = datetime.now(UTC)

                    # Dead pets: still poll (grave page stays current) but skip health updates
                    if pet.is_dead:
                        pet.last_checked_at = now
                        updated_count += 1
                        continue

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
                    pet.last_checked_at = now

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
                            now - health.last_commit_at
                        ).total_seconds() / 3600
                        if hours_since_commit < 24:
                            pet.last_fed_at = now

                    # Update commit streak
                    update_commit_streak(pet, health, now)

                    # Update grace period tracker and check death conditions
                    update_grace_period(pet, now)
                    should_die, cause = check_death_conditions(pet, now)
                    if should_die:
                        pet.is_dead = True
                        pet.died_at = now
                        pet.cause_of_death = cause
                        logger.info(
                            "pet_died",
                            pet_id=pet.id,
                            pet_name=pet.name,
                            repo=f"{pet.repo_owner}/{pet.repo_name}",
                            cause=cause,
                        )

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
                    rate_limited = True
                    logger.warning(
                        "poll_rate_limited",
                        pet_id=pet.id,
                        repo=f"{pet.repo_owner}/{pet.repo_name}",
                        reset_time=e.reset_time.isoformat() if e.reset_time else None,
                        message="GitHub API rate limit reached, stopping poll cycle",
                    )
                    error_messages.append(
                        f"Rate limited on {pet.repo_owner}/{pet.repo_name}"
                    )
                    # Stop polling to avoid hitting rate limits further
                    break

                except Exception as e:
                    error_count += 1
                    error_messages.append(f"{pet.repo_owner}/{pet.repo_name}: {e}")
                    logger.error(
                        "poll_pet_error",
                        pet_id=pet.id,
                        repo=f"{pet.repo_owner}/{pet.repo_name}",
                        error=str(e),
                    )
                    # Continue with other pets

            # Commit all changes
            await session.commit()

            # --- Alert checks ---
            if settings.alerting_enabled:
                await _run_alert_checks(
                    session=session,
                    total_pets=total_pets,
                    updated_count=updated_count,
                    error_count=error_count,
                    rate_limited=rate_limited,
                )

        final_status = "success"
    except Exception as e:
        final_status = "failed"
        error_messages.append(f"Unhandled error: {e}")
        logger.error("poll_failed", error=str(e))

    # Update the JobRun with results
    async with async_session_factory() as session:
        job_run_result = await session.get(JobRun, job_run_id)
        if job_run_result is not None:
            job_run_result.completed_at = datetime.now(UTC)
            job_run_result.status = final_status
            job_run_result.pets_processed = updated_count
            job_run_result.errors_count = error_count
            job_run_result.error_details = "\n".join(error_messages) if error_messages else None
            await session.commit()

    logger.info(
        "poll_completed",
        updated_count=updated_count,
        error_count=error_count,
        evolved_count=evolved_count,
        message="Repository health check complete",
    )


async def _run_alert_checks(
    session: AsyncSession,
    total_pets: int,
    updated_count: int,
    error_count: int,
    rate_limited: bool,
) -> None:
    """Run all alert condition checks after a poll cycle."""
    global _consecutive_poll_failures  # noqa: PLW0603

    checker = AlertChecker(session)

    # Track consecutive poll failures
    if error_count > 0 and updated_count == 0:
        _consecutive_poll_failures += 1
    else:
        _consecutive_poll_failures = 0
    await checker.check_poll_failures(_consecutive_poll_failures)

    # Error rate check
    total_attempted = updated_count + error_count
    await checker.check_error_rate(error_count, total_attempted)

    # Rate limit check (fire alert if rate-limited during this cycle)
    if rate_limited:
        await checker.check_github_rate_limit(0, 5000)
    else:
        await checker.check_github_rate_limit(settings.alert_github_rate_limit_threshold, 5000)

    # Dying pets check
    dying_result = await session.execute(
        select(func.count()).select_from(Pet).where(Pet.health == 0)
    )
    dying_count = dying_result.scalar() or 0
    await checker.check_dying_pets(dying_count, total_pets)

    # Database latency check
    start = time.monotonic()
    await session.execute(text("SELECT 1"))
    db_ms = (time.monotonic() - start) * 1000
    await checker.check_database_slow(db_ms)

    await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Startup
    logger.info("Starting GitHub Tamagotchi", version=__version__)

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=os.getenv("ENVIRONMENT", "production"),
            traces_sample_rate=0.1,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            send_default_pii=False,
        )
        logger.info("Sentry initialized")

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
app.include_router(alert_router)
app.include_router(auth_router)

# Mount the MCP server at /mcp
app.mount("/mcp", mcp_app)

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


OptionalUser = Annotated[User | None, Depends(get_optional_user)]


@app.get("/", response_class=HTMLResponse)
async def root(request: Request, user: OptionalUser) -> HTMLResponse:
    """Landing page."""
    return templates.TemplateResponse(
        request, "landing.html", {"user": user, "base_url": settings.base_url}
    )


DbSession = Annotated[AsyncSession, Depends(get_session)]


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, user: OptionalUser, session: DbSession) -> Response:
    """My Pets dashboard page."""
    if not user:
        return RedirectResponse(url="/auth/github", status_code=302)
    pets, _ = await pet_crud.get_pets(session, per_page=100, user_id=user.id)
    return templates.TemplateResponse(request, "dashboard.html", {"user": user, "pets": pets})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, user: OptionalUser) -> Response:
    """Repo selection page for pet registration."""
    if not user:
        return RedirectResponse(url="/auth/github", status_code=302)
    return templates.TemplateResponse(request, "register.html", {"user": user})


@app.get("/register/complete", response_class=HTMLResponse)
async def register_complete_page(
    request: Request,
    user: OptionalUser,
    owner: str = Query(...),
    repo: str = Query(...),
    pet_name: str = Query(...),
) -> Response:
    """Success page shown after pet registration with embed code."""
    if not user:
        return RedirectResponse(url="/auth/github", status_code=302)
    base_url = str(request.base_url).rstrip("/")
    embed_image_url = f"{base_url}/api/v1/pets/{owner}/{repo}/badge.svg"
    pet_page_url = f"{base_url}/pet/{owner}/{repo}"
    embed_code = f"[![{pet_name}]({embed_image_url})]({pet_page_url})"
    return templates.TemplateResponse(
        request,
        "register_complete.html",
        {
            "user": user,
            "owner": owner,
            "repo": repo,
            "pet_name": pet_name,
            "embed_code": embed_code,
            "embed_image_url": embed_image_url,
            "pet_page_url": pet_page_url,
        },
    )

@app.get("/pet/{repo_owner}/{repo_name}", response_class=HTMLResponse)
async def pet_profile(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user: OptionalUser,
    session: DbSession,
) -> HTMLResponse:
    """Public pet profile page."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found")

    # Build evolution timeline
    stages = list(PetStage)
    current_stage_idx = stages.index(PetStage(pet.stage))
    evolution_timeline = [
        {
            "stage": stage.value,
            "threshold": EVOLUTION_THRESHOLDS[stage],
            "reached": i <= current_stage_idx,
            "current": i == current_stage_idx,
        }
        for i, stage in enumerate(stages)
    ]

    # Build activity feed from available timestamps
    now = datetime.now(UTC)
    raw_activity: list[tuple[datetime, str, str]] = []
    if pet.last_fed_at:
        raw_activity.append((pet.last_fed_at, "Fed", "🍖"))
    if pet.last_checked_at:
        raw_activity.append((pet.last_checked_at, "Health checked", "🩺"))
    raw_activity.append((pet.created_at, "Pet created", "🥚"))
    raw_activity.sort(key=lambda x: x[0], reverse=True)
    activity_items = [
        {"event": ev, "timestamp": ts, "icon": icon}
        for ts, ev, icon in raw_activity[:10]
    ]

    # Calculate age in days (handle both tz-aware and naive datetimes from DB)
    created = pet.created_at
    if created.tzinfo is None:
        age_days = (now.replace(tzinfo=None) - created).days
    else:
        age_days = (now - created).days

    page_url = str(request.url)
    return templates.TemplateResponse(
        request,
        "pet_profile.html",
        {
            "user": user,
            "pet": pet,
            "age_days": age_days,
            "evolution_timeline": evolution_timeline,
            "activity_items": activity_items,
            "page_url": page_url,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "base_url": settings.base_url,
            "now_utc": now,
        },
        headers={"Cache-Control": "public, max-age=60"},
    )


AdminUser = Annotated[User, Depends(get_admin_user)]


@app.get("/admin/webhooks", response_class=HTMLResponse)
async def admin_webhook_log(
    request: Request,
    user: AdminUser,
    session: DbSession,
) -> HTMLResponse:
    """Admin page showing the last 100 webhook events."""
    result = await session.execute(
        select(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(100)
    )
    events = result.scalars().all()
    return templates.TemplateResponse(
        request,
        "admin_webhooks.html",
        {"user": user, "events": events},
    )


@app.get("/admin", response_class=HTMLResponse)
async def admin_overview(request: Request, user: AdminUser, session: DbSession) -> HTMLResponse:
    """Admin overview page with aggregate stats."""
    # Counts
    user_count_result = await session.execute(select(func.count()).select_from(User))
    total_users = user_count_result.scalar() or 0

    pet_count_result = await session.execute(select(func.count()).select_from(Pet))
    total_pets = pet_count_result.scalar() or 0

    # Health distribution
    healthy_result = await session.execute(
        select(func.count()).select_from(Pet).where(Pet.health >= 70)
    )
    health_healthy = healthy_result.scalar() or 0

    warning_result = await session.execute(
        select(func.count()).select_from(Pet).where(Pet.health >= 40, Pet.health < 70)
    )
    health_warning = warning_result.scalar() or 0

    critical_result = await session.execute(
        select(func.count()).select_from(Pet).where(Pet.health < 40)
    )
    health_critical = critical_result.scalar() or 0

    # Stage distribution
    stage_counts: dict[str, int] = {}
    for stage in PetStage:
        result = await session.execute(
            select(func.count()).select_from(Pet).where(Pet.stage == stage.value)
        )
        stage_counts[stage.value] = result.scalar() or 0

    # Most recently created pets (latest 5) with owner info
    recent_pets_result = await session.execute(
        select(Pet, User)
        .outerjoin(User, Pet.user_id == User.id)
        .order_by(Pet.created_at.desc())
        .limit(5)
    )
    recent_pets = [
        {"pet": row.Pet, "owner": row.User}
        for row in recent_pets_result
    ]

    return templates.TemplateResponse(
        request,
        "admin_overview.html",
        {
            "user": user,
            "total_users": total_users,
            "total_pets": total_pets,
            "health_healthy": health_healthy,
            "health_warning": health_warning,
            "health_critical": health_critical,
            "stage_counts": stage_counts,
            "recent_pets": recent_pets,
        },
    )


@app.get("/admin/pets", response_class=HTMLResponse)
async def admin_pets(
    request: Request,
    user: AdminUser,
    session: DbSession,
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """Admin pet gallery with pagination."""
    per_page = 20
    pets_with_owners, total = await pet_crud.get_pets_with_owners(
        session, page=page, per_page=per_page
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request,
        "admin_pets.html",
        {
            "user": user,
            "pets_with_owners": pets_with_owners,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@app.get("/admin/jobs", response_class=HTMLResponse)
async def admin_jobs(
    request: Request,
    user: AdminUser,
    session: DbSession,
) -> HTMLResponse:
    """Admin page showing the last 50 job runs."""
    result = await session.execute(
        select(JobRun).order_by(JobRun.started_at.desc()).limit(50)
    )
    job_runs = result.scalars().all()
    return templates.TemplateResponse(
        request,
        "admin_jobs.html",
        {"user": user, "job_runs": job_runs},
    )


@app.post("/admin/jobs/poll/trigger")
async def admin_trigger_poll(
    request: Request,
    user: AdminUser,
    background_tasks: BackgroundTasks,
) -> Response:
    """Manually trigger a poll run immediately."""
    triggered_by = f"manual:{user.github_login}"
    background_tasks.add_task(poll_repositories, triggered_by=triggered_by)
    return RedirectResponse(url="/admin/jobs", status_code=303)
