"""Tests for alert API endpoints."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from github_tamagotchi.models.pet import Base

_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
_session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _get_test_session() -> AsyncIterator[AsyncSession]:
    async with _session_factory() as session:
        yield session


def _create_alert_test_app():  # type: ignore[no-untyped-def]
    from fastapi import FastAPI

    from github_tamagotchi.api.alerts import alert_router
    from github_tamagotchi.core.database import get_session

    app = FastAPI()
    app.include_router(alert_router)
    app.dependency_overrides[get_session] = _get_test_session
    return app


@pytest.fixture
async def alert_client() -> AsyncIterator[AsyncClient]:
    app = _create_alert_test_app()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_with_alerts() -> AsyncIterator[AsyncSession]:
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _session_factory() as session:
        # Add some test alerts
        session.add(
            Alert(
                alert_type=AlertType.POLL_FAILED.value,
                severity=AlertSeverity.CRITICAL.value,
                status=AlertStatus.FIRING.value,
                message="Poll failed 3 times",
            )
        )
        session.add(
            Alert(
                alert_type=AlertType.HIGH_ERROR_RATE.value,
                severity=AlertSeverity.WARNING.value,
                status=AlertStatus.RESOLVED.value,
                message="Error rate was high",
            )
        )
        await session.commit()
        yield session
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_list_alerts(alert_client: AsyncClient, db_with_alerts: AsyncSession) -> None:
    resp = await alert_client.get("/api/v1/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


async def test_list_alerts_filter_by_status(
    alert_client: AsyncClient, db_with_alerts: AsyncSession
) -> None:
    resp = await alert_client.get("/api/v1/alerts?status=firing")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["alert_type"] == "poll_failed"


async def test_list_active_alerts(
    alert_client: AsyncClient, db_with_alerts: AsyncSession
) -> None:
    resp = await alert_client.get("/api/v1/alerts/active")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "firing"


async def test_get_alert_config(alert_client: AsyncClient) -> None:
    resp = await alert_client.get("/api/v1/alerts/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "poll_failure_threshold" in data
    assert "error_rate_threshold" in data


async def test_test_alert_no_channels(alert_client: AsyncClient) -> None:
    with patch(
        "github_tamagotchi.api.alerts.send_alert_notification",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = await alert_client.post("/api/v1/alerts/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is False


async def test_test_alert_with_channel(alert_client: AsyncClient) -> None:
    with patch(
        "github_tamagotchi.api.alerts.send_alert_notification",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = await alert_client.post("/api/v1/alerts/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is True
