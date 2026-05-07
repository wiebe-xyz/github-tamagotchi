"""Tests for comprehensive health check endpoints."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi import __version__
from github_tamagotchi.api.auth import get_admin_user
from github_tamagotchi.api.health import (
    CheckResult,
    _check_database,
    _check_github_api,
    _check_scheduler,
    _format_uptime,
    health_router,
)
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base
from tests.conftest import get_test_session, test_engine


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
        scheduler_ok = CheckResult(status="ok", next_poll_in="28m0s")

        with patch(
            "github_tamagotchi.api.health._check_scheduler",
            return_value=scheduler_ok,
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "database" in data["checks"]
        assert "scheduler" in data["checks"]
        assert "github_api" not in data["checks"]
        assert data["checks"]["database"]["status"] == "ok"
        assert data["checks"]["scheduler"]["status"] == "ok"

    async def test_readiness_503_when_critical_check_fails(
        self, async_client: AsyncClient
    ) -> None:
        """Readiness returns 503 when any critical check fails."""
        db_error = CheckResult(status="error", error="Connection refused")
        scheduler_ok = CheckResult(status="ok", next_poll_in="10m0s")

        with (
            patch(
                "github_tamagotchi.api.health._check_database",
                new_callable=AsyncMock,
                return_value=db_error,
            ),
            patch(
                "github_tamagotchi.api.health._check_scheduler",
                return_value=scheduler_ok,
            ),
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 503

    async def test_readiness_degraded_when_scheduler_degraded(
        self, async_client: AsyncClient
    ) -> None:
        """Readiness returns 200 with degraded when scheduler is degraded."""
        scheduler_degraded = CheckResult(
            status="degraded", next_poll_in="3600s overdue"
        )

        with patch(
            "github_tamagotchi.api.health._check_scheduler",
            return_value=scheduler_degraded,
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    async def test_readiness_includes_check_details(self, async_client: AsyncClient) -> None:
        """Readiness response includes latency and scheduler info."""
        scheduler_ok = CheckResult(status="ok", next_poll_in="14m30s")

        with patch(
            "github_tamagotchi.api.health._check_scheduler",
            return_value=scheduler_ok,
        ):
            response = await async_client.get("/api/v1/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["checks"]["database"]["latency_ms"] is not None
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

    async def test_detailed_unhealthy_when_db_error(
        self, admin_health_client: AsyncClient
    ) -> None:
        """Detailed endpoint returns unhealthy status when a check has error."""
        db_error = CheckResult(status="error", error="Connection refused")
        github_ok = CheckResult(status="ok", latency_ms=60.0, rate_limit_remaining=4700)
        scheduler_ok = CheckResult(status="ok", next_poll_in="20m0s")

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
            response = await admin_health_client.get("/api/v1/health/detailed")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"

    async def test_detailed_degraded_when_check_degraded(
        self, admin_health_client: AsyncClient
    ) -> None:
        """Detailed endpoint returns degraded status when a check is degraded."""
        github_degraded = CheckResult(
            status="degraded", latency_ms=60.0, rate_limit_remaining=50
        )
        scheduler_ok = CheckResult(status="ok", next_poll_in="20m0s")

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
            response = await admin_health_client.get("/api/v1/health/detailed")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"

    async def test_detailed_uptime_unknown_when_none(
        self, admin_health_client: AsyncClient
    ) -> None:
        """Detailed endpoint shows 'unknown' uptime when get_uptime_seconds returns None."""
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
            patch(
                "github_tamagotchi.api.health.get_uptime_seconds",
                return_value=None,
            ),
        ):
            response = await admin_health_client.get("/api/v1/health/detailed")

        assert response.status_code == 200
        data = response.json()
        assert data["uptime"] == "unknown"


class TestFormatUptime:
    """Tests for _format_uptime helper."""

    def test_seconds_only(self) -> None:
        assert _format_uptime(45) == "0m 45s"

    def test_minutes_and_seconds(self) -> None:
        assert _format_uptime(125) == "2m 5s"

    def test_hours_minutes_seconds(self) -> None:
        result = _format_uptime(3661)
        assert result == "1h 1m 1s"

    def test_days(self) -> None:
        result = _format_uptime(86400 + 3600)
        assert result == "1d 1h 0m"


class TestCheckDatabase:
    """Tests for _check_database internal function."""

    async def test_ok_when_query_succeeds(self, test_db: AsyncSession) -> None:
        """Returns ok status when SELECT 1 succeeds."""
        result = await _check_database(test_db)
        assert result.status == "ok"
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    async def test_error_when_exception(self) -> None:
        """Returns error status when session raises an exception."""
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Connection refused")
        result = await _check_database(mock_session)
        assert result.status == "error"
        assert result.error == "Connection refused"

    async def test_degraded_when_slow(self, test_db: AsyncSession) -> None:
        """Returns degraded status when latency exceeds 1000ms."""
        call_count = 0

        def mock_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 0.0
            return 1.1  # 1100ms latency

        with patch("github_tamagotchi.api.health.time.monotonic", side_effect=mock_monotonic):
            result = await _check_database(test_db)

        assert result.status == "degraded"
        assert result.latency_ms == 1100.0


class TestCheckGithubApi:
    """Tests for _check_github_api internal function."""

    async def test_ok_when_rate_limit_ample(self) -> None:
        """Returns ok when GitHub returns 200 and rate limit is above threshold."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"rate": {"remaining": 4500}}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _check_github_api()

        assert result.status == "ok"
        assert result.rate_limit_remaining == 4500

    async def test_degraded_when_rate_limit_low(self) -> None:
        """Returns degraded when rate limit is below 100."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"rate": {"remaining": 50}}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _check_github_api()

        assert result.status == "degraded"
        assert result.rate_limit_remaining == 50

    async def test_error_when_non_200(self) -> None:
        """Returns error when GitHub returns non-200 status."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _check_github_api()

        assert result.status == "error"
        assert "503" in (result.error or "")

    async def test_error_on_network_exception(self) -> None:
        """Returns error when network request raises an exception."""
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=Exception("Connection timeout"))
            mock_client_cls.return_value = mock_client

            result = await _check_github_api()

        assert result.status == "error"
        assert "Connection timeout" in (result.error or "")

    async def test_uses_token_when_configured(self) -> None:
        """Sends Authorization header when github_token is configured."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"rate": {"remaining": 4500}}

        with (
            patch("httpx.AsyncClient") as mock_client_cls,
            patch(
                "github_tamagotchi.api.health.settings"
            ) as mock_settings,
        ):
            mock_settings.github_token = "mytoken"
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await _check_github_api()

        assert result.status == "ok"
        call_kwargs = mock_client.get.call_args
        headers = call_kwargs[1].get("headers") or call_kwargs[0][1]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer mytoken"


class TestCheckScheduler:
    """Tests for _check_scheduler internal function."""

    def test_ok_when_job_running_soon(self) -> None:
        """Returns ok when job has a future next_run_time."""
        from datetime import UTC, datetime, timedelta

        mock_job = MagicMock()
        mock_job.next_run_time = datetime.now(UTC) + timedelta(minutes=10)

        with patch("github_tamagotchi.api.health.scheduler") as mock_scheduler:
            mock_scheduler.get_job.return_value = mock_job
            result = _check_scheduler()

        assert result.status == "ok"
        assert result.next_poll_in is not None

    def test_ok_when_next_run_has_minutes(self) -> None:
        """Returns ok with Xm Ys format for next run times over a minute away."""
        from datetime import UTC, datetime, timedelta

        mock_job = MagicMock()
        mock_job.next_run_time = datetime.now(UTC) + timedelta(seconds=125)

        with patch("github_tamagotchi.api.health.scheduler") as mock_scheduler:
            mock_scheduler.get_job.return_value = mock_job
            result = _check_scheduler()

        assert result.status == "ok"
        assert "m" in (result.next_poll_in or "")

    def test_ok_when_next_run_seconds_only(self) -> None:
        """Returns ok with Xs format for next run times less than a minute away."""
        from datetime import UTC, datetime, timedelta

        mock_job = MagicMock()
        mock_job.next_run_time = datetime.now(UTC) + timedelta(seconds=30)

        with patch("github_tamagotchi.api.health.scheduler") as mock_scheduler:
            mock_scheduler.get_job.return_value = mock_job
            result = _check_scheduler()

        assert result.status == "ok"
        # Result is "Xs" where X is close to 30 (timing may vary by 1-2s)
        assert result.next_poll_in is not None
        assert result.next_poll_in.endswith("s")
        assert "m" not in result.next_poll_in

    def test_ok_running_when_slightly_overdue(self) -> None:
        """Returns ok with 'running' when job is slightly overdue but within threshold."""
        from datetime import UTC, datetime, timedelta

        mock_job = MagicMock()
        mock_job.next_run_time = datetime.now(UTC) - timedelta(seconds=30)

        with (
            patch("github_tamagotchi.api.health.scheduler") as mock_scheduler,
            patch("github_tamagotchi.api.health.settings") as mock_settings,
        ):
            mock_settings.github_poll_interval_minutes = 30
            mock_scheduler.get_job.return_value = mock_job
            result = _check_scheduler()

        assert result.status == "ok"
        assert result.next_poll_in == "running"

    def test_degraded_when_overdue(self) -> None:
        """Returns degraded when job is more than 2x interval overdue."""
        from datetime import UTC, datetime, timedelta

        mock_job = MagicMock()
        # More than 2 * 30 minutes = 60 minutes overdue
        mock_job.next_run_time = datetime.now(UTC) - timedelta(hours=2)

        with (
            patch("github_tamagotchi.api.health.scheduler") as mock_scheduler,
            patch("github_tamagotchi.api.health.settings") as mock_settings,
        ):
            mock_settings.github_poll_interval_minutes = 30
            mock_scheduler.get_job.return_value = mock_job
            result = _check_scheduler()

        assert result.status == "degraded"
        assert "overdue" in (result.next_poll_in or "")

    def test_error_when_job_not_found(self) -> None:
        """Returns error when poll_repositories job is not found."""
        with patch("github_tamagotchi.api.health.scheduler") as mock_scheduler:
            mock_scheduler.get_job.return_value = None
            result = _check_scheduler()

        assert result.status == "error"
        assert result.error == "Job not found"

    def test_error_when_no_next_run_time(self) -> None:
        """Returns error when job has no next_run_time."""
        mock_job = MagicMock()
        mock_job.next_run_time = None

        with patch("github_tamagotchi.api.health.scheduler") as mock_scheduler:
            mock_scheduler.get_job.return_value = mock_job
            result = _check_scheduler()

        assert result.status == "error"
        assert result.error == "Job has no next run time"

    def test_error_on_exception(self) -> None:
        """Returns error when scheduler raises an exception."""
        with patch("github_tamagotchi.api.health.scheduler") as mock_scheduler:
            mock_scheduler.get_job.side_effect = Exception("Scheduler crash")
            result = _check_scheduler()

        assert result.status == "error"
        assert "Scheduler crash" in (result.error or "")
