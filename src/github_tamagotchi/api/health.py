"""Health check endpoints for k8s probes and monitoring."""

import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi import __version__
from github_tamagotchi.api.auth import get_admin_user
from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import get_session
from github_tamagotchi.core.scheduler import get_uptime_seconds, scheduler
from github_tamagotchi.models.job_run import JobRun
from github_tamagotchi.models.pet import Pet
from github_tamagotchi.models.user import User
from github_tamagotchi.models.webhook_event import WebhookEvent

logger = structlog.get_logger()

health_router = APIRouter(prefix="/api/v1/health", tags=["health"])

DbSession = Annotated[AsyncSession, Depends(get_session)]
AdminUser = Annotated[User, Depends(get_admin_user)]


class LivenessResponse(BaseModel):
    """Simple liveness response."""

    status: str


class CheckResult(BaseModel):
    """Result of a single dependency check."""

    status: str
    latency_ms: float | None = None
    rate_limit_remaining: int | None = None
    next_poll_in: str | None = None
    error: str | None = None


class ReadinessResponse(BaseModel):
    """Readiness check response with dependency statuses."""

    status: str
    checks: dict[str, CheckResult]


class PetStats(BaseModel):
    """Pet statistics."""

    total_pets: int
    active_pets: int
    dead_pets: int


class ActivityStats(BaseModel):
    """Activity statistics for the last hour."""

    polls_last_hour: int
    webhooks_last_hour: int
    errors_last_hour: int


class DetailedResponse(BaseModel):
    """Full system status for admin monitoring."""

    status: str
    version: str
    uptime: str
    checks: dict[str, CheckResult]
    stats: dict[str, Any]


def _format_uptime(seconds: float) -> str:
    """Format seconds into a human-readable uptime string."""
    td = timedelta(seconds=int(seconds))
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"


async def _check_database(session: AsyncSession) -> CheckResult:
    """Check database connectivity and measure latency."""
    start = time.monotonic()
    try:
        await session.execute(text("SELECT 1"))
        latency_ms = (time.monotonic() - start) * 1000
        if latency_ms > 1000:
            return CheckResult(status="degraded", latency_ms=round(latency_ms, 2))
        return CheckResult(status="ok", latency_ms=round(latency_ms, 2))
    except Exception as exc:
        logger.warning("Database health check failed", error=str(exc))
        return CheckResult(status="error", error=str(exc))


async def _check_github_api() -> CheckResult:
    """Check GitHub API availability via rate limit endpoint."""
    try:
        headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            start = time.monotonic()
            resp = await client.get("https://api.github.com/rate_limit", headers=headers)
            latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            return CheckResult(
                status="error",
                latency_ms=round(latency_ms, 2),
                error=f"HTTP {resp.status_code}",
            )
        data = resp.json()
        remaining = data.get("rate", {}).get("remaining", 0)
        if remaining < 100:
            return CheckResult(
                status="degraded",
                latency_ms=round(latency_ms, 2),
                rate_limit_remaining=remaining,
            )
        return CheckResult(
            status="ok",
            latency_ms=round(latency_ms, 2),
            rate_limit_remaining=remaining,
        )
    except Exception as exc:
        logger.warning("GitHub API health check failed", error=str(exc))
        return CheckResult(status="error", error=str(exc))


async def _check_storage() -> CheckResult:
    """Check MinIO/S3 storage connectivity."""
    if not settings.minio_endpoint:
        return CheckResult(status="ok", error="not configured (optional)")
    try:
        from github_tamagotchi.services.storage import StorageService

        storage = StorageService()
        start = time.monotonic()
        await storage.ensure_bucket_exists()
        latency_ms = (time.monotonic() - start) * 1000
        if latency_ms > 2000:
            return CheckResult(status="degraded", latency_ms=round(latency_ms, 2))
        return CheckResult(status="ok", latency_ms=round(latency_ms, 2))
    except Exception as exc:
        logger.warning("Storage health check failed", error=str(exc))
        return CheckResult(status="error", error=str(exc))


def _check_scheduler() -> CheckResult:
    """Check if the poll_repositories job is scheduled and running."""
    try:
        job = scheduler.get_job("poll_repositories")
        if job is None:
            return CheckResult(status="error", error="Job not found")
        next_run = job.next_run_time
        if next_run is None:
            return CheckResult(status="error", error="Job has no next run time")
        now = datetime.now(UTC)
        seconds_until = (next_run - now).total_seconds()
        interval_seconds = settings.github_poll_interval_minutes * 60
        # Consider degraded if next run is more than 2x the interval overdue
        if seconds_until < -(interval_seconds * 2):
            return CheckResult(
                status="degraded",
                next_poll_in=f"{int(-seconds_until)}s overdue",
            )
        if seconds_until < 0:
            next_poll_str = "running"
        else:
            minutes, secs = divmod(int(seconds_until), 60)
            next_poll_str = f"{minutes}m{secs}s" if minutes else f"{secs}s"
        return CheckResult(status="ok", next_poll_in=next_poll_str)
    except Exception as exc:
        logger.warning("Scheduler health check failed", error=str(exc))
        return CheckResult(status="error", error=str(exc))


@health_router.get("", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Liveness probe — returns 200 if the process is alive."""
    return LivenessResponse(status="ok")


@health_router.get("/ready", response_model=ReadinessResponse)
async def readiness(session: DbSession) -> ReadinessResponse:
    """Readiness probe — checks all critical dependencies."""
    db_check = await _check_database(session)
    github_check = await _check_github_api()
    scheduler_check = _check_scheduler()
    storage_check = await _check_storage()

    checks = {
        "database": db_check,
        "github_api": github_check,
        "scheduler": scheduler_check,
        "storage": storage_check,
    }

    all_ok = all(c.status == "ok" for c in checks.values())
    any_error = any(c.status == "error" for c in checks.values())

    if any_error:
        overall = "unhealthy"
    elif not all_ok:
        overall = "degraded"
    else:
        overall = "healthy"

    if any_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ReadinessResponse(status=overall, checks=checks).model_dump(),
        )

    return ReadinessResponse(status=overall, checks=checks)


@health_router.get("/detailed", response_model=DetailedResponse)
async def detailed(
    session: DbSession,
    _admin: AdminUser,
) -> DetailedResponse:
    """Full system status — requires admin authentication."""
    db_check = await _check_database(session)
    github_check = await _check_github_api()
    scheduler_check = _check_scheduler()
    storage_check = await _check_storage()

    checks = {
        "database": db_check,
        "github_api": github_check,
        "scheduler": scheduler_check,
        "storage": storage_check,
    }

    all_ok = all(c.status == "ok" for c in checks.values())
    any_error = any(c.status == "error" for c in checks.values())

    if any_error:
        overall = "unhealthy"
    elif not all_ok:
        overall = "degraded"
    else:
        overall = "healthy"

    # Pet stats
    total_pets = (await session.execute(select(func.count()).select_from(Pet))).scalar() or 0
    dead_pets = (
        await session.execute(select(func.count()).select_from(Pet).where(Pet.is_dead.is_(True)))
    ).scalar() or 0
    active_pets = total_pets - dead_pets

    # Activity stats (last hour)
    one_hour_ago = datetime.now(UTC) - timedelta(hours=1)

    polls_last_hour = (
        await session.execute(
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.job_name == "poll_repositories")
            .where(JobRun.started_at >= one_hour_ago)
        )
    ).scalar() or 0

    webhooks_last_hour = (
        await session.execute(
            select(func.count())
            .select_from(WebhookEvent)
            .where(WebhookEvent.created_at >= one_hour_ago)
        )
    ).scalar() or 0

    errors_last_hour = (
        await session.execute(
            select(func.sum(JobRun.errors_count))
            .select_from(JobRun)
            .where(JobRun.started_at >= one_hour_ago)
        )
    ).scalar() or 0

    uptime_seconds = get_uptime_seconds()
    uptime_str = _format_uptime(uptime_seconds) if uptime_seconds is not None else "unknown"

    return DetailedResponse(
        status=overall,
        version=__version__,
        uptime=uptime_str,
        checks=checks,
        stats={
            "total_pets": total_pets,
            "active_pets": active_pets,
            "dead_pets": dead_pets,
            "polls_last_hour": polls_last_hour,
            "webhooks_last_hour": webhooks_last_hour,
            "errors_last_hour": int(errors_last_hour),
        },
    )
