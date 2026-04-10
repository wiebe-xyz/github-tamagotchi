"""Tests for comprehensive health check endpoints."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from github_tamagotchi import __version__
from github_tamagotchi.api.health import CheckResult, health_router
from github_tamagotchi.api.auth import get_admin_user
from github_tamagotchi.core.database import get_session
from tests.conftest import get_test_session, test_engine
from github_tamagotchi.models.pet import Base


class TestLivenessEndpoint:
    """Tests for GET /api/v1/health (liveness probe)."""

    def test_liveness_returns_200(self, client: TestClient) -> None:
        """Liveness endpoint returns 200 OK."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_liveness_returns_ok_status(self, client: TestClient) -> None:
        """Liveness endpoint returns ok status (no dependency checks)."""
        response = client.get("/api/v1/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_liveness_has_no_dependency_fields(self, client: TestClient) -> None:
        """Liveness endpoint does not expose database or other check fields."""
        response = client.get("/api/v1/health")
        data = response.json()
        assert "database" not in data
        assert "checks" not in data


class TestReadinessEndpoint:
    """Tests for GET /api/v1/health/ready (readiness probe)."""

    async def test_readiness_healthy_when_all_checks_pass(
        self, async_client: AsyncClient
    ) -> None:
        """Readiness returns 200 when all dependency checks pass."""
        github_ok = CheckResult(status="ok", latency_ms=50.0, rate_limit_remaining=4500)
        scheduler_ok = CheckResult(status="ok", next_poll_in="28m0s")

        with (
            patch(
                "github_tamagotchi.api.health._check_github_api",
                new_callable=AsyncMock,
                return_value=github_ok,
            ),
            patch(
                "github_tamagotchi.api.health._check_scheduler",
                return_value=scheduler_ok,
            ),
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "database" in data["checks"]
        assert "github_api" in data["checks"]
        assert "scheduler" in data["checks"]
        assert data["checks"]["database"]["status"] == "ok"
        assert data["checks"]["github_api"]["status"] == "ok"
        assert data["checks"]["scheduler"]["status"] == "ok"

    async def test_readiness_503_when_critical_check_fails(
        self, async_client: AsyncClient
    ) -> None:
        """Readiness returns 503 when any critical check fails."""
        db_error = CheckResult(status="error", error="Connection refused")
        github_ok = CheckResult(status="ok", latency_ms=45.0, rate_limit_remaining=4000)
        scheduler_ok = CheckResult(status="ok", next_poll_in="10m0s")

        with (
            patch(
                "github_tamagotchi.api.health._check_database",
                new_callable=AsyncMock,
                return_value=db_error,
            ),
            patch(
                "github_tamagotchi.api.health._check_github_api",
                new_callable=AsyncMock,
                return_value=github_ok,
            ),
            patch(
                "github_tamagotchi.api.health._check_scheduler",
                return_value=scheduler_ok,
            ),
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 503

    async def test_readiness_degraded_when_github_rate_limit_low(
        self, async_client: AsyncClient
    ) -> None:
        """Readiness returns 200 with degraded when GitHub rate limit is low."""
        github_degraded = CheckResult(status="degraded", latency_ms=40.0, rate_limit_remaining=50)
        scheduler_ok = CheckResult(status="ok", next_poll_in="5m0s")

        with (
            patch(
                "github_tamagotchi.api.health._check_github_api",
                new_callable=AsyncMock,
                return_value=github_degraded,
            ),
            patch(
                "github_tamagotchi.api.health._check_scheduler",
                return_value=scheduler_ok,
            ),
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    async def test_readiness_includes_check_details(self, async_client: AsyncClient) -> None:
        """Readiness response includes latency and rate limit info."""
        github_ok = CheckResult(status="ok", latency_ms=55.3, rate_limit_remaining=4800)
        scheduler_ok = CheckResult(status="ok", next_poll_in="14m30s")

        with (
            patch(
                "github_tamagotchi.api.health._check_github_api",
                new_callable=AsyncMock,
                return_value=github_ok,
            ),
            patch(
                "github_tamagotchi.api.health._check_scheduler",
                return_value=scheduler_ok,
            ),
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["checks"]["database"]["latency_ms"] is not None
        assert data["checks"]["github_api"]["rate_limit_remaining"] == 4800
        assert data["checks"]["scheduler"]["next_poll_in"] == "14m30s"


@pytest.fixture
async def admin_health_client() -> AsyncIterator[AsyncClient]:
    """Async client with admin dependency overridden for health endpoint tests."""
    mock_admin_user = MagicMock()
    mock_admin_user.is_admin = True

    app = FastAPI(title="Health Admin Test")
    app.include_router(health_router)
    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_admin_user] = lambda: mock_admin_user

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestDetailedEndpoint:
    """Tests for GET /api/v1/health/detailed (admin endpoint)."""

    async def test_detailed_requires_auth(self, async_client: AsyncClient) -> None:
        """Detailed endpoint returns 401 without authentication."""
        response = await async_client.get("/api/v1/health/detailed")
        # FastAPI returns 401 or 403 depending on auth setup
        assert response.status_code in (401, 403)

    async def test_detailed_returns_full_stats_for_admin(
        self, admin_health_client: AsyncClient
    ) -> None:
        """Detailed endpoint returns version, uptime, checks, and pet stats."""
        github_ok = CheckResult(status="ok", latency_ms=60.0, rate_limit_remaining=4700)
        scheduler_ok = CheckResult(status="ok", next_poll_in="20m0s")

        with (
            patch(
                "github_tamagotchi.api.health._check_github_api",
                new_callable=AsyncMock,
                return_value=github_ok,
            ),
            patch(
                "github_tamagotchi.api.health._check_scheduler",
                return_value=scheduler_ok,
            ),
        ):
            response = await admin_health_client.get("/api/v1/health/detailed")

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == __version__
        assert "uptime" in data
        assert "checks" in data
        assert "stats" in data
        stats = data["stats"]
        assert "total_pets" in stats
        assert "active_pets" in stats
        assert "dead_pets" in stats
        assert "polls_last_hour" in stats
        assert "webhooks_last_hour" in stats
        assert "errors_last_hour" in stats
