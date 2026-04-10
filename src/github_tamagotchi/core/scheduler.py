"""Shared scheduler instance for background jobs."""

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

# Set during application startup
app_start_time: datetime | None = None


def set_start_time() -> None:
    """Record the application startup time."""
    global app_start_time
    app_start_time = datetime.now(UTC)


def get_uptime_seconds() -> float | None:
    """Return seconds since startup, or None if not started."""
    if app_start_time is None:
        return None
    return (datetime.now(UTC) - app_start_time).total_seconds()
