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
from typing import Annotated, Any

import sentry_sdk
import structlog
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import github_tamagotchi.core.bugbarn as bb
from github_tamagotchi import __version__
from github_tamagotchi import metrics as metrics_service
from github_tamagotchi.api.alerts import alert_router
from github_tamagotchi.api.auth import auth_router, get_admin_user, get_optional_user
from github_tamagotchi.api.exception_handlers import register_exception_handlers
from github_tamagotchi.api.health import health_router
from github_tamagotchi.api.routes import router
from github_tamagotchi.api.routes.v1.push import router as push_router
from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import async_session_factory, close_database, get_session
from github_tamagotchi.core.logging import (
    configure_logging,
    setup_log_transport,
    shutdown_log_transport,
)
from github_tamagotchi.core.scheduler import scheduler, set_start_time
from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.crud.contributor_relationship import upsert_contributor_relationship
from github_tamagotchi.crud.milestone import create_milestone
from github_tamagotchi.mcp.server import get_mcp_server
from github_tamagotchi.models.job_run import JobRun
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.models.webhook_event import WebhookEvent
from github_tamagotchi.services import image_queue
from github_tamagotchi.services.achievements import check_and_unlock_achievements
from github_tamagotchi.services.alerting import AlertChecker
from github_tamagotchi.services.contributor_relationships import build_contributor_updates
from github_tamagotchi.services.github import GitHubService, RateLimitError, RepoInsights
from github_tamagotchi.services.pet_logic import (
    DEATH_GRACE_PERIOD_DAYS,
    EVOLUTION_THRESHOLDS,
    calculate_experience,
    calculate_health_delta,
    calculate_mood,
    check_death_conditions,
    get_next_stage,
    update_commit_streak,
    update_grace_period,
)
from github_tamagotchi.services.push_notifications import (
    notify_dying_and_dead_pets,
    notify_unhappy_pets,
)

# Configure structured logging before anything else logs
configure_logging()

# Set up paths for templates and static files
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["funnelbarn_api_key"] = settings.funnelbarn_api_key
templates.env.globals["bugbarn_endpoint"] = settings.bugbarn_endpoint
templates.env.globals["bugbarn_api_key"] = settings.bugbarn_api_key
templates.env.globals["bugbarn_project"] = settings.bugbarn_project

logger = structlog.get_logger()

from github_tamagotchi.core.telemetry import get_tracer  # noqa: E402

_tracer = get_tracer(__name__)

# Track consecutive poll failures for alerting
_consecutive_poll_failures = 0


async def _update_single_pet(
    pet: Pet,
    session: AsyncSession,
    github_service: GitHubService,
) -> bool:
    """Fetch health metrics and update a single pet's state.

    Returns True if the pet was successfully updated, False on error.
    The caller is responsible for committing the session.
    """
    with _tracer.start_as_current_span(
        "update_single_pet",
        attributes={
            "pet.id": str(pet.id),
            "pet.name": pet.name,
            "pet.repo": f"{pet.repo_owner}/{pet.repo_name}",
            "pet.stage": pet.stage,
            "pet.health_before": pet.health,
        },
    ) as span:
        return await _update_single_pet_inner(pet, session, github_service, span)


async def _update_single_pet_inner(
    pet: Pet,
    session: AsyncSession,
    github_service: GitHubService,
    span: Any,
) -> bool:
    """Inner implementation of _update_single_pet with span context."""
    now = datetime.now(UTC)

    # Dead pets: still poll (grave page stays current) but skip health updates
    if pet.is_dead:
        pet.last_checked_at = now
        return True

    # Fetch health metrics from GitHub
    health = await github_service.get_repo_health(pet.repo_owner, pet.repo_name)

    # Calculate state changes
    health_delta = calculate_health_delta(health)
    experience_gained = calculate_experience(health)
    was_critical = pet.health < 5
    new_health = max(0, min(100, pet.health + health_delta))
    new_experience = pet.experience + experience_gained
    new_mood = calculate_mood(health, new_health)

    # Check for evolution
    current_stage = PetStage(pet.stage)
    new_stage = get_next_stage(current_stage, new_experience)

    # Track low-health recoveries (Ghost skin unlock condition)
    if was_critical and new_health >= 5:
        pet.low_health_recoveries += 1
        logger.info(
            "pet_low_health_recovery",
            pet_id=pet.id,
            pet_name=pet.name,
            repo=f"{pet.repo_owner}/{pet.repo_name}",
            low_health_recoveries=pet.low_health_recoveries,
        )

    # Update pet
    pet.health = new_health
    pet.experience = new_experience
    pet.mood = new_mood.value
    pet.last_checked_at = now

    # Handle evolution
    if new_stage != current_stage:
        pet.stage = new_stage.value
        metrics_service.evolutions_total.labels(
            from_stage=current_stage.value,
            to_stage=new_stage.value,
        ).inc()
        await create_milestone(
            session, pet, current_stage.value, new_stage.value, new_experience
        )
        span.add_event(
            "pet_evolved",
            {"from_stage": current_stage.value, "to_stage": new_stage.value},
        )
        logger.info(
            "pet_evolved",
            pet_id=pet.id,
            pet_name=pet.name,
            repo=f"{pet.repo_owner}/{pet.repo_name}",
            old_stage=current_stage.value,
            new_stage=new_stage.value,
            experience=new_experience,
        )

    # Store last-known release, contributor, dependent, and popularity snapshots
    pet.last_release_count = health.release_count_30d
    pet.last_contributor_count = health.contributor_count
    pet.dependent_count = health.dependent_count
    pet.star_count = health.star_count
    pet.fork_count = health.fork_count

    # Update last_fed_at if there was a recent commit
    if health.last_commit_at:
        hours_since_commit = (now - health.last_commit_at).total_seconds() / 3600
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
        metrics_service.deaths_total.labels(cause=cause).inc()
        span.add_event("pet_died", {"cause": cause})
        logger.info(
            "pet_died",
            pet_id=pet.id,
            pet_name=pet.name,
            repo=f"{pet.repo_owner}/{pet.repo_name}",
            cause=cause,
        )

    # Check and unlock achievements based on updated pet state
    newly_unlocked = await check_and_unlock_achievements(
        pet,
        session,
        star_count=health.star_count,
        fork_count=health.fork_count,
    )
    if newly_unlocked:
        logger.info(
            "achievements_unlocked",
            pet_id=pet.id,
            pet_name=pet.name,
            achievements=newly_unlocked,
        )

    # Update contributor relationships from GitHub activity
    try:
        activity = await github_service.get_all_contributor_activity(
            pet.repo_owner, pet.repo_name
        )
        contributor_updates = build_contributor_updates(activity, now)
        for update in contributor_updates:
            await upsert_contributor_relationship(
                db=session,
                pet_id=pet.id,
                github_username=update.github_username,
                score=update.score,
                standing=update.standing,
                last_activity=update.last_activity,
                good_deeds=update.good_deeds,
                sins=update.sins,
            )
    except RateLimitError:
        raise
    except Exception as e:
        logger.warning(
            "contributor_relationship_update_failed",
            pet_id=pet.id,
            repo=f"{pet.repo_owner}/{pet.repo_name}",
            error=str(e),
            exc_info=True,
        )

    span.set_attribute("pet.health_after", new_health)
    span.set_attribute("pet.health_delta", health_delta)
    span.set_attribute("pet.experience_gained", experience_gained)
    span.set_attribute("pet.mood", new_mood.value)
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
    return True


async def poll_repositories(triggered_by: str = "scheduler") -> None:
    """Periodic task to check all registered repositories."""
    global _consecutive_poll_failures  # noqa: PLW0603

    with _tracer.start_as_current_span(
        "poll_repositories",
        attributes={"poll.triggered_by": triggered_by},
    ) as poll_span:
        await _poll_repositories_inner(triggered_by, poll_span)


async def _poll_repositories_inner(triggered_by: str, poll_span: Any) -> None:
    """Inner implementation of poll_repositories with span context."""
    global _consecutive_poll_failures  # noqa: PLW0603

    logger.info(
        "poll_started",
        message="Starting repository health check poll",
        triggered_by=triggered_by,
    )

    github_service = GitHubService()
    updated_count = 0
    error_count = 0
    rate_limited = False
    error_messages: list[str] = []
    poll_start = time.monotonic()

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
            # Query all real pets; placeholders are skipped until claimed.
            result = await session.execute(select(Pet).where(Pet.is_placeholder.is_(False)))
            pets = result.scalars().all()
            total_pets = len(pets)

            logger.info("poll_pets_found", pet_count=total_pets)

            for pet in pets:
                try:
                    await _update_single_pet(pet, session, github_service)
                    updated_count += 1
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
                    break
                except Exception as e:
                    error_count += 1
                    metrics_service.poll_errors_total.inc()
                    error_messages.append(f"{pet.repo_owner}/{pet.repo_name}: {e}")
                    logger.error(
                        "poll_pet_error",
                        pet_id=pet.id,
                        repo=f"{pet.repo_owner}/{pet.repo_name}",
                        error=str(e),
                        exc_info=True,
                    )

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

            # --- Web push notifications for unhappy pets ---
            if settings.vapid_private_key:
                await notify_unhappy_pets(session)
                await notify_dying_and_dead_pets(session)

            # --- Business metrics gauges ---
            now_ts = datetime.now(UTC)
            seven_days_ago = now_ts.timestamp() - 7 * 86400
            dead_count = 0
            dying_count = 0
            active_count = 0
            # Refresh pet stage/mood gauge counts
            stage_mood_counts: dict[tuple[str, str], int] = {}
            for pet in pets:
                key = (pet.stage, pet.mood)
                stage_mood_counts[key] = stage_mood_counts.get(key, 0) + 1
                if pet.is_dead:
                    dead_count += 1
                elif pet.grace_period_started is not None:
                    dying_count += 1
                if (
                    pet.last_fed_at is not None
                    and pet.last_fed_at.timestamp() >= seven_days_ago
                ):
                    active_count += 1
            for (stage, mood), count in stage_mood_counts.items():
                metrics_service.pets_total.labels(stage=stage, mood=mood).set(count)
            metrics_service.pets_dead_total.set(dead_count)
            metrics_service.pets_dying.set(dying_count)
            metrics_service.pets_active.set(active_count)

        final_status = "success"
    except Exception as e:
        final_status = "failed"
        error_messages.append(f"Unhandled error: {e}")
        logger.error("poll_failed", error=str(e), exc_info=True)

    # Record poll duration and processed count
    poll_duration = time.monotonic() - poll_start
    metrics_service.poll_duration_seconds.observe(poll_duration)
    metrics_service.poll_pets_processed.set(updated_count)
    if final_status == "success":
        metrics_service.poll_last_success_timestamp.set(time.time())

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

    poll_span.set_attribute("poll.pet_count", updated_count + error_count)
    poll_span.set_attribute("poll.updated_count", updated_count)
    poll_span.set_attribute("poll.error_count", error_count)
    poll_span.set_attribute("poll.rate_limited", rate_limited)
    poll_span.set_attribute("poll.duration_seconds", poll_duration)
    poll_span.set_attribute("poll.status", final_status)

    logger.info(
        "poll_completed",
        updated_count=updated_count,
        error_count=error_count,
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

    if settings.bugbarn_endpoint and settings.bugbarn_api_key:
        environment = os.getenv("ENVIRONMENT", "production")
        bb.init(
            api_key=settings.bugbarn_api_key,
            endpoint=settings.bugbarn_endpoint,
            project_slug=settings.bugbarn_project,
            environment=environment,
            install_excepthook=True,
        )
        setup_log_transport(
            logs_url=f"{settings.bugbarn_endpoint.rstrip('/')}/api/v1/logs",
            api_key=settings.bugbarn_api_key,
            project=settings.bugbarn_project,
        )
        logger.info("BugBarn initialized", project=settings.bugbarn_project, env=environment)

    from github_tamagotchi.core.telemetry import init_telemetry

    init_telemetry(app)

    set_start_time()

    # Log VAPID key status for push notifications
    if settings.vapid_private_key:
        logger.info("Push notifications enabled (VAPID configured)")
    else:
        logger.warning(
            "Push notifications disabled — VAPID_PRIVATE_KEY not set. "
            "Run: python -m github_tamagotchi.scripts.gen_vapid_keys"
        )

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
    from github_tamagotchi.core.telemetry import shutdown_telemetry

    shutdown_telemetry()
    logger.info("Flushing error tracking and log transports")
    bb.shutdown()
    shutdown_log_transport()
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
app.include_router(health_router)
app.include_router(push_router)

# Mount the MCP server at /mcp
app.mount("/mcp", mcp_app)

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


register_exception_handlers(app, templates)


# --- PWA endpoints ---

_pwa_icon_cache: dict[int, bytes] = {}


@app.get("/pwa/icon/{size}.png", include_in_schema=False)
async def pwa_icon(size: int) -> Response:
    """Serve a generated PWA app icon at the requested size."""
    valid_sizes = {72, 96, 128, 144, 152, 180, 192, 384, 512}
    if size not in valid_sizes:
        raise HTTPException(status_code=404)

    if size not in _pwa_icon_cache:
        import io

        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Indigo background circle (safe zone for maskable icons)
        pad = int(size * 0.04)
        draw.ellipse([pad, pad, size - pad, size - pad], fill=(99, 102, 241))

        # White egg-shaped body
        cx, cy = size / 2, size * 0.52
        bw, bh = size * 0.52, size * 0.62
        draw.ellipse([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], fill=(255, 255, 255))

        # Eyes
        es = size * 0.065
        ey = cy - bh * 0.08
        for ex in [cx - bw * 0.19, cx + bw * 0.19]:
            draw.ellipse([ex - es / 2, ey - es / 2, ex + es / 2, ey + es / 2], fill=(99, 102, 241))

        # Smile
        sw = bw * 0.33
        sy = cy + bh * 0.13
        lw = max(2, int(size * 0.025))
        draw.arc(
            [cx - sw / 2, sy - sw * 0.22, cx + sw / 2, sy + sw * 0.22],
            start=15, end=165, fill=(99, 102, 241), width=lw,
        )

        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        _pwa_icon_cache[size] = buf.getvalue()

    return Response(
        content=_pwa_icon_cache[size],
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> Response:
    """Serve the service worker from the static directory at root scope."""
    sw_path = BASE_DIR / "static" / "sw.js"
    return Response(
        content=sw_path.read_bytes(),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


@app.get("/manifest.json", include_in_schema=False)
async def root_manifest() -> Response:
    """Serve the root PWA manifest."""
    manifest_path = BASE_DIR / "static" / "manifest.json"
    return Response(
        content=manifest_path.read_text(),
        media_type="application/manifest+json",
    )


@app.get("/pet/{repo_owner}/{repo_name}/manifest.json", include_in_schema=False)
async def pet_manifest(
    repo_owner: str,
    repo_name: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Per-pet PWA manifest so users can install a specific pet to their home screen."""
    import json as _json

    result = await session.execute(
        select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
    )
    pet = result.scalar_one_or_none()

    if pet:
        name = f"{pet.name} · Tamagotchi"
        short_name = pet.name[:12]
        description = f"Your {pet.stage} pet for {repo_owner}/{repo_name}."
        stage = pet.stage if not pet.is_dead else "egg"
        sprite_url = f"/api/v1/pets/{repo_owner}/{repo_name}/image/{stage}"
    else:
        name = f"{repo_owner}/{repo_name} · Tamagotchi"
        short_name = repo_name[:12]
        description = f"Tamagotchi pet for {repo_owner}/{repo_name}."
        sprite_url = "/pwa/icon/512.png"

    manifest = {
        "name": name,
        "short_name": short_name,
        "description": description,
        "start_url": f"/pet/{repo_owner}/{repo_name}",
        "scope": "/",
        "id": f"/pet/{repo_owner}/{repo_name}",
        "display": "standalone",
        "background_color": "#0f0f1a",
        "theme_color": "#6366f1",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": sprite_url,
                "sizes": "1024x1024",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": "/pwa/icon/192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": "/pwa/icon/512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }

    return Response(
        content=_json.dumps(manifest),
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=300"},
    )




@app.middleware("http")
async def metrics_middleware(request: Request, call_next: object) -> Response:
    """Track HTTP request counts and durations."""
    start = time.monotonic()
    response: Response = await call_next(request)  # type: ignore[operator]
    duration = time.monotonic() - start

    route = request.scope.get("route")
    endpoint = route.path if route else request.url.path

    metrics_service.http_requests_total.labels(
        method=request.method,
        endpoint=endpoint,
        status=str(response.status_code),
    ).inc()
    metrics_service.http_request_duration_seconds.labels(endpoint=endpoint).observe(duration)

    return response


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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
    return templates.TemplateResponse(
        request, "dashboard.html", {"user": user, "pets": pets, "now_utc": datetime.now(UTC)}
    )


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
    base = settings.base_url.rstrip("/")
    embed_image_url = f"{base}/api/v1/pets/{owner}/{repo}/badge.svg"
    pet_page_url = f"{base}/pet/{owner}/{repo}"
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


@app.get("/dashboard/{username}", response_class=HTMLResponse)
async def contributor_dashboard(
    request: Request,
    username: str,
    user: OptionalUser,
    session: DbSession,
) -> HTMLResponse:
    """Personal pet dashboard showing a contributor's standing across all pets."""
    from sqlalchemy import select as sa_select

    result = await session.execute(sa_select(Pet))
    all_pets = result.scalars().all()

    # Pets owned by this user (their GitHub repos)
    my_pets = [p for p in all_pets if p.repo_owner.lower() == username.lower()]

    # Other pets (living) — check if user contributes
    other_pets = [p for p in all_pets if p.repo_owner.lower() != username.lower() and not p.is_dead]

    github_service = GitHubService()
    team_pets = []
    for pet in other_pets:
        try:
            stats = await github_service.get_contributor_stats(
                pet.repo_owner, pet.repo_name, username
            )
            if stats.days_since_last_commit is None:
                continue  # never contributed here
            if stats.is_top_contributor:
                standing = "favorite"
            elif stats.commits_30d > 0:
                standing = "good"
            else:
                standing = "absent"
            team_pets.append(
                {
                    "pet": pet,
                    "standing": standing,
                    "commits_30d": stats.commits_30d,
                    "days_since": stats.days_since_last_commit,
                }
            )
        except Exception:
            logger.warning(
                "contributor_dashboard_error",
                username=username,
                repo=f"{pet.repo_owner}/{pet.repo_name}",
                exc_info=True,
            )

    favorite_count = sum(1 for t in team_pets if t["standing"] == "favorite")
    doghouse_count = sum(1 for t in team_pets if t["standing"] == "doghouse")
    total_score: int = sum(t["commits_30d"] for t in team_pets)  # type: ignore[misc]

    return templates.TemplateResponse(
        request,
        "contributor_dashboard.html",
        {
            "user": user,
            "username": username,
            "my_pets": my_pets,
            "team_pets": team_pets,
            "total_repos": len(team_pets) + len(my_pets),
            "favorite_count": favorite_count,
            "doghouse_count": doghouse_count,
            "total_score": total_score,
        },
    )


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(
    request: Request, user: OptionalUser, session: DbSession
) -> HTMLResponse:
    """Public leaderboard page showing top pets by category."""
    from github_tamagotchi.crud.pet import get_leaderboard

    categories = [
        {
            "id": "most_experienced",
            "title": "Most Experienced",
            "description": "Highest total XP earned",
            "value_field": "experience",
            "value_label": "XP",
        },
        {
            "id": "longest_streak",
            "title": "Longest Streak",
            "description": "Most consecutive days with commits",
            "value_field": "longest_streak",
            "value_label": "days",
        },
    ]

    leaderboard_data = []
    for cat in categories:
        pets = await get_leaderboard(session, cat["id"], limit=10)
        entries = [
            {
                "rank": i + 1,
                "pet": p,
                "value": getattr(p, cat["value_field"]),
            }
            for i, p in enumerate(pets)
        ]
        leaderboard_data.append(
            {
                "id": cat["id"],
                "title": cat["title"],
                "description": cat["description"],
                "value_label": cat["value_label"],
                "entries": entries,
            }
        )

    return templates.TemplateResponse(
        request,
        "leaderboard.html",
        {
            "user": user,
            "leaderboard_data": leaderboard_data,
        },
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/org/{org_name}", response_class=HTMLResponse)
async def org_overview(
    request: Request,
    org_name: str,
    user: OptionalUser,
    session: DbSession,
) -> HTMLResponse:
    """Org-wide pet overview: all pets, aggregate health, and contributor leaderboard."""
    import asyncio

    from github_tamagotchi.crud.pet import get_org_pets

    pets = await get_org_pets(session, org_name)

    # Aggregate health stats
    total = len(pets)
    healthy = sum(1 for p in pets if p.health >= 70 and not p.is_dead)
    hungry = sum(1 for p in pets if 30 <= p.health < 70 and not p.is_dead)
    sick = sum(1 for p in pets if p.health < 30 and not p.is_dead)
    dead = sum(1 for p in pets if p.is_dead)
    avg_health = int(sum(p.health for p in pets) / total) if total else 0

    # Neglected repos: health < 30 or dead
    neglected = [p for p in pets if p.is_dead or p.health < 30]

    # Fetch top contributor per pet in parallel (best-effort)
    top_contributors: list[str | None] = []
    if pets:
        tasks = [
            GitHubService().get_top_contributor(p.repo_owner, p.repo_name) for p in pets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                logger.warning(
                    "top_contributor_fetch_failed",
                    repo=f"{pets[i].repo_owner}/{pets[i].repo_name}",
                    error=str(r),
                )
                top_contributors.append(None)
            else:
                top_contributors.append(r if isinstance(r, str) else None)

    # Build per-pet display entries
    pet_entries = [
        {"pet": p, "top_caretaker": top_contributors[i] if i < len(top_contributors) else None}
        for i, p in enumerate(pets)
    ]

    # Build org contributor leaderboard (count of repos per top contributor)
    caretaker_counts: dict[str, int] = {}
    for entry in pet_entries:
        caretaker = entry["top_caretaker"]
        if isinstance(caretaker, str):
            caretaker_counts[caretaker] = caretaker_counts.get(caretaker, 0) + 1
    org_leaderboard = sorted(caretaker_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    return templates.TemplateResponse(
        request,
        "org_overview.html",
        {
            "user": user,
            "org_name": org_name,
            "pet_entries": pet_entries,
            "total": total,
            "healthy": healthy,
            "hungry": hungry,
            "sick": sick,
            "dead": dead,
            "avg_health": avg_health,
            "neglected": neglected,
            "org_leaderboard": org_leaderboard,
        },
    )


@app.get("/graveyard", response_class=HTMLResponse)
async def graveyard_page(
    request: Request,
    user: OptionalUser,
    session: DbSession,
    page: int = 1,
) -> HTMLResponse:
    """Public graveyard — all dead pets."""
    from github_tamagotchi.repositories.graveyard import get_dead_pets

    per_page = 20
    graves, total = await get_dead_pets(session, page, per_page)
    return templates.TemplateResponse(
        request,
        "graveyard.html",
        {
            "user": user,
            "graves": graves,
            "total": total,
            "page": page,
            "per_page": per_page,
            "username": None,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/graveyard/{username}", response_class=HTMLResponse)
async def graveyard_user_page(
    request: Request,
    username: str,
    user: OptionalUser,
    session: DbSession,
    page: int = 1,
) -> HTMLResponse:
    """Personal graveyard for a user's dead pets."""
    from github_tamagotchi.repositories.graveyard import get_dead_pets_by_user

    per_page = 20
    graves, total = await get_dead_pets_by_user(session, username, page, per_page)
    return templates.TemplateResponse(
        request,
        "graveyard.html",
        {
            "user": user,
            "graves": graves,
            "total": total,
            "page": page,
            "per_page": per_page,
            "username": username,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/graveyard/{username}/{repo_name}", response_class=HTMLResponse, response_model=None)
async def graveyard_grave_page(
    request: Request,
    username: str,
    repo_name: str,
    user: OptionalUser,
    session: DbSession,
) -> HTMLResponse | RedirectResponse:
    """Memorial page for a single dead pet."""
    from github_tamagotchi.repositories.graveyard import get_grave
    from github_tamagotchi.repositories.pet import get_pet_by_repo

    pet = await get_grave(session, username, repo_name)
    if not pet:
        alive = await get_pet_by_repo(session, username, repo_name)
        if alive:
            return RedirectResponse(f"/pet/{username}/{repo_name}")
        raise HTTPException(status_code=404, detail="Grave not found")

    cause_labels = {
        "neglect": "Died of neglect — the commits stopped coming",
        "abandonment": "Abandoned — the repository went dark",
    }
    cause_label = cause_labels.get(pet.cause_of_death or "", pet.cause_of_death or "Cause unknown")

    now = datetime.now(UTC)
    age_days = (pet.died_at - pet.created_at).days if pet.died_at and pet.created_at else 0
    would_be_days = (now - pet.created_at).days if pet.created_at else 0
    is_owner = user is not None and pet.user_id is not None and user.id == pet.user_id

    return templates.TemplateResponse(
        request,
        "graveyard_grave.html",
        {
            "user": user,
            "pet": pet,
            "cause_label": cause_label,
            "age_days": age_days,
            "would_be_days": would_be_days,
            "is_owner": is_owner,
            "base_url": str(request.base_url).rstrip("/"),
        },
        headers={"Cache-Control": "public, max-age=300"},
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

    # Calculate days until death if pet is in grace period
    days_until_death: int | None = None
    if pet.health == 0 and pet.grace_period_started and not pet.is_dead:
        gps = pet.grace_period_started
        now_naive = now.replace(tzinfo=None)
        gps_naive = gps.replace(tzinfo=None) if gps.tzinfo is not None else gps
        elapsed = (now_naive - gps_naive).days
        days_until_death = max(DEATH_GRACE_PERIOD_DAYS - elapsed, 0)

    # Fetch contributor relationships
    from github_tamagotchi.crud.contributor_relationship import get_contributors_for_pet

    contributor_relationships = await get_contributors_for_pet(session, pet.id)

    user_has_pets = False
    if user:
        own_pets = await session.execute(
            select(func.count()).select_from(Pet).where(Pet.user_id == user.id)
        )
        user_has_pets = (own_pets.scalar_one() or 0) > 0

    page_url = str(request.url)
    return templates.TemplateResponse(
        request,
        "pet_profile.html",
        {
            "user": user,
            "user_has_pets": user_has_pets,
            "pet": pet,
            "age_days": age_days,
            "evolution_timeline": evolution_timeline,
            "activity_items": activity_items,
            "page_url": page_url,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "base_url": settings.base_url,
            "now_utc": now,
            "contributor_relationships": contributor_relationships,
            "days_until_death": days_until_death,
        },
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/pet/{repo_owner}/{repo_name}/insights", response_class=HTMLResponse)
async def pet_insights(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user: OptionalUser,
    session: DbSession,
) -> HTMLResponse:
    """Repo health insights page for a pet."""
    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found")

    github_service = GitHubService()
    insights: RepoInsights | None = None
    try:
        insights = await github_service.get_repo_insights(repo_owner, repo_name)
    except RateLimitError:
        logger.warning("insights_rate_limited", repo=f"{repo_owner}/{repo_name}")
    except Exception:
        logger.warning("insights_fetch_failed", repo=f"{repo_owner}/{repo_name}", exc_info=True)

    # Build pet correlation messages based on insights
    pet_correlations: list[str] = []
    if insights:
        if insights.total_commits_30d == 0:
            pet_correlations.append(f"{pet.name} has been starving — no commits in the last month.")
        elif insights.total_commits_30d < 5:
            pet_correlations.append(
                f"Only {insights.total_commits_30d} commits this month kept {pet.name} barely fed."
            )
        else:
            pet_correlations.append(
                f"{insights.total_commits_30d} commits this month kept {pet.name} well nourished."
            )

        if insights.ci_pass_rate is not None:
            pct = int(insights.ci_pass_rate * 100)
            if pct < 60:
                pet_correlations.append(
                    f"CI failures ({pct}% pass rate) have been stressing {pet.name} out."
                )
            elif pct >= 90:
                pet_correlations.append(
                    f"Great CI health ({pct}% pass rate) keeps {pet.name} thriving."
                )

        if insights.avg_pr_merge_hours is not None:
            days = insights.avg_pr_merge_hours / 24
            if days > 7:
                pet_correlations.append(
                    f"PRs sitting open for {days:.1f} days on average make {pet.name} anxious."
                )

    return templates.TemplateResponse(
        request,
        "pet_insights.html",
        {
            "user": user,
            "pet": pet,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "insights": insights,
            "pet_correlations": pet_correlations,
            "base_url": settings.base_url,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/pet/{repo_owner}/{repo_name}/admin", response_class=HTMLResponse)
async def pet_admin_page(
    request: Request,
    repo_owner: str,
    repo_name: str,
    user: OptionalUser,
    session: DbSession,
) -> Response:
    """Pet admin panel — accessible only to the repo's GitHub admin."""
    from sqlalchemy import select as _select

    from github_tamagotchi.models.excluded_contributor import ExcludedContributor
    from github_tamagotchi.services.token_encryption import decrypt_token

    if not user:
        return RedirectResponse(url="/auth/github", status_code=302)

    pet = await pet_crud.get_pet_by_repo(session, repo_owner, repo_name)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found")

    # Check repo admin permission (site admins bypass)
    is_repo_admin = user.is_admin
    if not is_repo_admin and user.encrypted_token:
        token = decrypt_token(user.encrypted_token)
        gh = GitHubService(token=token)
        try:
            permission = await gh.get_repo_permission(repo_owner, repo_name, user.github_login)
            is_repo_admin = permission == "admin"
        except Exception:
            logger.warning(
                "repo_permission_check_failed",
                repo=f"{repo_owner}/{repo_name}",
                user=user.github_login,
                exc_info=True,
            )

    if not is_repo_admin:
        raise HTTPException(status_code=403, detail="Repo admin permission required")

    result = await session.execute(
        _select(ExcludedContributor).where(ExcludedContributor.pet_id == pet.id)
    )
    excluded_contributors = list(result.scalars().all())

    return templates.TemplateResponse(
        request,
        "pet_admin.html",
        {
            "user": user,
            "pet": pet,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "excluded_contributors": excluded_contributors,
            "base_url": settings.base_url,
        },
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


@app.get("/admin/achievements", response_class=HTMLResponse)
async def admin_achievements(
    request: Request,
    user: AdminUser,
    session: DbSession,
) -> HTMLResponse:
    """Admin page showing achievement statistics."""
    from sqlalchemy import desc

    from github_tamagotchi.models.achievement import PetAchievement
    from github_tamagotchi.services.achievements import ACHIEVEMENT_ORDER, ACHIEVEMENTS

    # Total achievements unlocked
    total_result = await session.execute(
        select(func.count()).select_from(PetAchievement)
    )
    total_unlocked = total_result.scalar() or 0

    # Most commonly unlocked achievements
    popular_result = await session.execute(
        select(PetAchievement.achievement_id, func.count().label("count"))
        .group_by(PetAchievement.achievement_id)
        .order_by(desc("count"))
    )
    popular_rows = popular_result.all()
    popular = [
        {
            "achievement_id": row.achievement_id,
            "name": ACHIEVEMENTS.get(row.achievement_id, {}).get("name", row.achievement_id),
            "icon": ACHIEVEMENTS.get(row.achievement_id, {}).get("icon", ""),
            "count": row.count,
        }
        for row in popular_rows
    ]

    # Recent unlocks (last 20) with pet info
    recent_result = await session.execute(
        select(PetAchievement, Pet)
        .join(Pet, PetAchievement.pet_id == Pet.id)
        .order_by(PetAchievement.unlocked_at.desc())
        .limit(20)
    )
    recent_unlocks = [
        {
            "pet": row.Pet,
            "achievement_id": row.PetAchievement.achievement_id,
            "name": ACHIEVEMENTS.get(row.PetAchievement.achievement_id, {}).get(
                "name", row.PetAchievement.achievement_id
            ),
            "icon": ACHIEVEMENTS.get(row.PetAchievement.achievement_id, {}).get("icon", ""),
            "unlocked_at": row.PetAchievement.unlocked_at,
        }
        for row in recent_result
    ]

    return templates.TemplateResponse(
        request,
        "admin_achievements.html",
        {
            "user": user,
            "total_unlocked": total_unlocked,
            "popular": popular,
            "recent_unlocks": recent_unlocks,
            "achievements": ACHIEVEMENTS,
            "achievement_order": ACHIEVEMENT_ORDER,
        },
    )


@app.get("/admin/sprites", response_class=HTMLResponse)
async def admin_sprites(
    request: Request,
    user: AdminUser,
    session: DbSession,
) -> HTMLResponse:
    """Admin page listing all pets with their full sprite sheets."""
    pets_result = await session.execute(
        select(Pet).order_by(Pet.repo_owner, Pet.repo_name)
    )
    pets = pets_result.scalars().all()
    stages = [s.value for s in PetStage]
    from github_tamagotchi.services.sprite_sheet import SPRITE_FRAMES
    frame_names = [name for _, name, _ in SPRITE_FRAMES]
    return templates.TemplateResponse(
        request,
        "admin_sprites.html",
        {"user": user, "pets": pets, "stages": stages, "frame_names": frame_names},
    )


@app.post("/admin/sprites/regenerate")
async def admin_sprites_regenerate(
    request: Request,
    user: AdminUser,
    session: DbSession,
) -> Response:
    """Queue image regeneration. Per-pet: {repo_owner, repo_name}. All: {stage: 'all'}."""
    body = await request.json()

    if "repo_owner" in body and "repo_name" in body:
        pet_result = await session.execute(
            select(Pet).where(
                Pet.repo_owner == body["repo_owner"],
                Pet.repo_name == body["repo_name"],
            )
        )
        pet = pet_result.scalar_one_or_none()
        if not pet:
            return JSONResponse({"error": "Pet not found"}, status_code=404)
        total_queued = 0
        for stage in PetStage:
            await image_queue.create_job(session, pet.id, stage.value)
            total_queued += 1
        return JSONResponse({"queued": total_queued})

    stage_param = body.get("stage", "all")
    if stage_param != "all":
        return JSONResponse({"error": f"Unknown stage: {stage_param}"}, status_code=400)

    total_queued = 0
    pets_result = await session.execute(select(Pet))
    all_pets = pets_result.scalars().all()
    for pet in all_pets:
        for stage in PetStage:
            await image_queue.create_job(session, pet.id, stage.value)
            total_queued += 1

    return JSONResponse({"queued": total_queued, "stage": "all"})
