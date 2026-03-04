"""Alerting service: checks conditions, manages state, and dispatches notifications."""

from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.config import settings
from github_tamagotchi.models.alert import (
    ALERT_SEVERITY,
    Alert,
    AlertStatus,
    AlertType,
)
from github_tamagotchi.services.notifier import send_alert_notification, send_resolved_notification

logger = structlog.get_logger()


async def _get_active_alert(session: AsyncSession, alert_type: AlertType) -> Alert | None:
    """Get an active (firing) alert of the given type."""
    result = await session.execute(
        select(Alert).where(
            Alert.alert_type == alert_type.value,
            Alert.status == AlertStatus.FIRING.value,
        )
    )
    return result.scalar_one_or_none()


async def fire_alert(
    session: AsyncSession,
    alert_type: AlertType,
    message: str,
    details: str | None = None,
) -> bool:
    """Fire an alert if not already active for this type.

    Returns True if new alert created.
    """
    existing = await _get_active_alert(session, alert_type)
    if existing:
        logger.debug("alert_already_firing", alert_type=alert_type.value)
        return False

    severity = ALERT_SEVERITY[alert_type]
    alert = Alert(
        alert_type=alert_type.value,
        severity=severity.value,
        status=AlertStatus.FIRING.value,
        message=message,
        details=details,
    )
    session.add(alert)
    await session.flush()

    await send_alert_notification(
        severity=severity.value,
        alert_type=alert_type.value,
        message=message,
        details=details,
    )

    logger.warning("alert_fired", alert_type=alert_type.value, message=message)
    return True


async def resolve_alert(
    session: AsyncSession,
    alert_type: AlertType,
    message: str | None = None,
) -> bool:
    """Resolve an active alert. Returns True if an alert was resolved."""
    existing = await _get_active_alert(session, alert_type)
    if not existing:
        return False

    existing.status = AlertStatus.RESOLVED.value
    existing.resolved_at = datetime.now(UTC)
    await session.flush()

    resolve_msg = message or f"{alert_type.value} has recovered."
    await send_resolved_notification(alert_type=alert_type.value, message=resolve_msg)

    logger.info("alert_resolved", alert_type=alert_type.value)
    return True


class AlertChecker:
    """Evaluates alert conditions against current system state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_poll_failures(self, consecutive_failures: int) -> None:
        """Check if poll failures exceed threshold."""
        if consecutive_failures >= settings.alert_poll_failure_threshold:
            await fire_alert(
                self.session,
                AlertType.POLL_FAILED,
                f"Repository poll has failed {consecutive_failures} consecutive times.",
                details=f"Threshold: {settings.alert_poll_failure_threshold}",
            )
        elif consecutive_failures == 0:
            await resolve_alert(
                self.session,
                AlertType.POLL_FAILED,
                "Poll job has recovered and is running successfully.",
            )

    async def check_github_rate_limit(self, remaining: int, limit: int) -> None:
        """Check if GitHub API rate limit is low."""
        if remaining < settings.alert_github_rate_limit_threshold:
            await fire_alert(
                self.session,
                AlertType.GITHUB_RATE_LIMITED,
                f"GitHub API rate limit low: {remaining}/{limit} remaining.",
                details=f"Threshold: {settings.alert_github_rate_limit_threshold}",
            )
        elif remaining >= settings.alert_github_rate_limit_threshold:
            await resolve_alert(
                self.session,
                AlertType.GITHUB_RATE_LIMITED,
                f"GitHub API rate limit recovered: {remaining}/{limit} remaining.",
            )

    async def check_error_rate(self, errors: int, total: int) -> None:
        """Check if error rate exceeds threshold."""
        if total == 0:
            return
        rate = errors / total
        if rate > settings.alert_error_rate_threshold:
            pct = f"{rate:.1%}"
            await fire_alert(
                self.session,
                AlertType.HIGH_ERROR_RATE,
                f"High error rate: {pct} ({errors}/{total} in last poll cycle).",
                details=f"Threshold: {settings.alert_error_rate_threshold:.0%}",
            )
        else:
            await resolve_alert(
                self.session,
                AlertType.HIGH_ERROR_RATE,
                f"Error rate back to normal: {errors}/{total}.",
            )

    async def check_dying_pets(self, dying_count: int, total_count: int) -> None:
        """Check if too many pets are in a dying state (health == 0)."""
        if total_count == 0:
            return
        pct = dying_count / total_count
        if pct > settings.alert_dying_pets_pct:
            await fire_alert(
                self.session,
                AlertType.MANY_DYING_PETS,
                f"{dying_count}/{total_count} pets ({pct:.0%}) are dying (health=0).",
                details=f"Threshold: {settings.alert_dying_pets_pct:.0%}",
            )
        else:
            await resolve_alert(
                self.session,
                AlertType.MANY_DYING_PETS,
                "Pet health levels have improved.",
            )

    async def check_pet_death_spike(self, deaths_24h: int) -> None:
        """Check for a spike in pet deaths in the last 24 hours."""
        if deaths_24h >= settings.alert_death_spike_count:
            await fire_alert(
                self.session,
                AlertType.PET_DEATH_SPIKE,
                f"{deaths_24h} pets reached health=0 in the last 24 hours.",
                details=f"Threshold: {settings.alert_death_spike_count}",
            )
        else:
            await resolve_alert(
                self.session,
                AlertType.PET_DEATH_SPIKE,
                "Pet death rate has returned to normal.",
            )

    async def check_database_slow(self, query_time_ms: float) -> None:
        """Check if database query time exceeds threshold."""
        if query_time_ms > settings.alert_db_slow_query_ms:
            await fire_alert(
                self.session,
                AlertType.DATABASE_SLOW,
                f"Database query took {query_time_ms:.0f}ms.",
                details=f"Threshold: {settings.alert_db_slow_query_ms}ms",
            )
        else:
            await resolve_alert(
                self.session,
                AlertType.DATABASE_SLOW,
                "Database performance has recovered.",
            )
