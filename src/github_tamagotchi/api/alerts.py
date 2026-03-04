"""API routes for alert management."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.core.config import settings
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.alert import Alert, AlertStatus
from github_tamagotchi.services.notifier import send_alert_notification

DbSession = Annotated[AsyncSession, Depends(get_session)]

alert_router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


class AlertResponse(BaseModel):
    """Response model for an alert."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_type: str
    severity: str
    status: str
    message: str
    details: str | None
    fired_at: datetime
    resolved_at: datetime | None


class AlertListResponse(BaseModel):
    """Paginated alert list response."""

    items: list[AlertResponse]
    total: int


class AlertConfigResponse(BaseModel):
    """Current alerting configuration."""

    enabled: bool
    has_slack_webhook: bool
    has_discord_webhook: bool
    poll_failure_threshold: int
    error_rate_threshold: float
    github_rate_limit_threshold: int
    db_slow_query_ms: int
    dying_pets_pct: float
    death_spike_count: int


class TestAlertResponse(BaseModel):
    """Response for test alert endpoint."""

    sent: bool
    message: str


@alert_router.get("", response_model=AlertListResponse)
async def list_alerts(
    session: DbSession,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AlertListResponse:
    """List alerts, optionally filtered by status."""
    query = select(Alert).order_by(Alert.fired_at.desc()).limit(limit)
    if status:
        query = query.where(Alert.status == status)
    result = await session.execute(query)
    alerts = list(result.scalars().all())

    count_query = select(Alert)
    if status:
        count_query = count_query.where(Alert.status == status)
    count_result = await session.execute(count_query)
    total = len(list(count_result.scalars().all()))

    return AlertListResponse(
        items=[AlertResponse.model_validate(a) for a in alerts],
        total=total,
    )


@alert_router.get("/active", response_model=AlertListResponse)
async def list_active_alerts(session: DbSession) -> AlertListResponse:
    """List currently firing alerts."""
    query = (
        select(Alert)
        .where(Alert.status == AlertStatus.FIRING.value)
        .order_by(Alert.fired_at.desc())
    )
    result = await session.execute(query)
    alerts = list(result.scalars().all())
    return AlertListResponse(
        items=[AlertResponse.model_validate(a) for a in alerts],
        total=len(alerts),
    )


@alert_router.get("/config", response_model=AlertConfigResponse)
async def get_alert_config() -> AlertConfigResponse:
    """Get current alerting configuration."""
    return AlertConfigResponse(
        enabled=settings.alerting_enabled,
        has_slack_webhook=settings.alert_slack_webhook is not None,
        has_discord_webhook=settings.alert_discord_webhook is not None,
        poll_failure_threshold=settings.alert_poll_failure_threshold,
        error_rate_threshold=settings.alert_error_rate_threshold,
        github_rate_limit_threshold=settings.alert_github_rate_limit_threshold,
        db_slow_query_ms=settings.alert_db_slow_query_ms,
        dying_pets_pct=settings.alert_dying_pets_pct,
        death_spike_count=settings.alert_death_spike_count,
    )


@alert_router.post("/test", response_model=TestAlertResponse)
async def send_test_alert() -> TestAlertResponse:
    """Send a test alert to all configured channels."""
    sent = await send_alert_notification(
        severity="warning",
        alert_type="test_alert",
        message="This is a test alert from GitHub Tamagotchi.",
        details="If you see this, your alert channels are working correctly.",
    )
    if sent:
        return TestAlertResponse(sent=True, message="Test alert sent successfully.")
    return TestAlertResponse(
        sent=False, message="No alert channels configured or alerting disabled."
    )
