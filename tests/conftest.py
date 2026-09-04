"""Test fixtures and configuration."""

import os

# MCP auth (mcp/server.py) builds its GitHubProvider once at import time from
# these settings — real deployments always have them (the website's own
# GitHub login already depends on them), but nothing in CI/local test runs
# sets them, and a missing client_id/secret means mcp.server falls back to
# no auth at all. Tests that exercise the real auth chain mock the actual
# GitHub API verification call, so fake-but-present values are fine here —
# must be set before any github_tamagotchi import triggers settings to load.
os.environ.setdefault("GITHUB_OAUTH_CLIENT_ID", "test-github-oauth-client-id")
os.environ.setdefault("GITHUB_OAUTH_CLIENT_SECRET", "test-github-oauth-client-secret")

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi import __version__
from github_tamagotchi.api.exception_handlers import register_exception_handlers
from github_tamagotchi.api.health import health_router
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session

# Import all models to ensure they're registered with Base.metadata
from github_tamagotchi.models import (  # noqa: F401
    ContributorRelationship,
    ImageGenerationJob,
    Pet,
    PetAchievement,
    User,
)
from github_tamagotchi.models.pet import Base
from github_tamagotchi.services.github import RepoHealth

# Use SQLite for testing (in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

test_session_factory = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_test_session() -> AsyncIterator[AsyncSession]:
    """Get a test database session."""
    async with test_session_factory() as session:
        yield session


def create_api_test_app() -> FastAPI:
    """Create a test FastAPI app for API testing (no templates/static)."""
    test_app = FastAPI(title="GitHub Tamagotchi Test")

    # Include the production API routers
    test_app.include_router(router)
    test_app.include_router(health_router)

    # Override the database session dependency
    test_app.dependency_overrides[get_session] = get_test_session

    # Register domain exception → HTTP status handlers
    register_exception_handlers(test_app)

    # Add root endpoint (production uses templates, test returns JSON)
    @test_app.get("/")
    async def root() -> dict[str, str]:
        return {
            "name": "GitHub Tamagotchi",
            "version": __version__,
            "docs": "/docs",
        }

    return test_app


@asynccontextmanager
async def empty_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Empty lifespan that doesn't start the scheduler."""
    yield


@pytest.fixture
async def test_db() -> AsyncIterator[AsyncSession]:
    """Create test database tables and provide a session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    """Create async test client for API testing with test database."""
    test_app = create_api_test_app()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_tables() -> None:
    """Helper to create all database tables."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_tables() -> None:
    """Helper to drop all database tables."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Create sync test client for production app testing (with templates/static)."""
    import importlib
    import sys

    import github_tamagotchi.services.image_queue

    # Create database tables
    asyncio.run(_create_tables())

    # Mock run_worker to wait for stop event or cancellation
    async def mock_run_worker(
        session_factory: object,
        stop_event: asyncio.Event | None = None,
        poll_interval: float | None = None,
    ) -> None:
        try:
            if stop_event:
                await stop_event.wait()
        except asyncio.CancelledError:
            pass

    # Patch at module level before reloading main
    original_run_worker = github_tamagotchi.services.image_queue.run_worker
    github_tamagotchi.services.image_queue.run_worker = mock_run_worker

    # Patch the scheduler
    with patch("github_tamagotchi.core.scheduler.scheduler") as mock_scheduler:
        mock_scheduler.start = lambda: None
        mock_scheduler.shutdown = lambda: None
        mock_scheduler.add_job = lambda *args, **kwargs: None

        # Reload main module to pick up the mocked run_worker
        if "github_tamagotchi.main" in sys.modules:
            del sys.modules["github_tamagotchi.main"]
        main_module = importlib.import_module("github_tamagotchi.main")
        app = main_module.app

        # Override database dependency
        app.dependency_overrides[get_session] = get_test_session

        with TestClient(app) as tc:
            yield tc

        # Clean up overrides
        app.dependency_overrides.clear()

    # Restore original
    github_tamagotchi.services.image_queue.run_worker = original_run_worker

    # Drop database tables
    asyncio.run(_drop_tables())


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_engine() -> AsyncIterator[None]:
    """Cleanup test engine after all tests."""
    yield
    await test_engine.dispose()


@pytest.fixture(autouse=True)
def _reset_mcp_play_cooldowns() -> Iterator[None]:
    """play_with_pet's rate limit is in-process state keyed by pet id
    (github_tamagotchi.mcp.server._last_played_at) — fine in production
    (single active pod), but SQLite reuses rowids across tests that each
    drop/recreate the pets table, so a pet in one test can spuriously
    inherit another test's cooldown unless this is cleared globally,
    not just within whichever test file happens to exercise play_with_pet.
    """
    from github_tamagotchi.mcp import server as mcp_server_module

    mcp_server_module._last_played_at.clear()
    yield
    mcp_server_module._last_played_at.clear()


@pytest.fixture(autouse=True)
def _default_pets_awake() -> Iterator[None]:
    """Default every pet to "awake" for tests that don't care about sleep.

    `sleep.is_asleep` gates on the real wall-clock UTC hour, so leaving it
    unmocked would make ~9/24 of any given day's CI runs spuriously exercise
    the "asleep" branch of feed_pet/play_with_pet/calculate_mood_with_care.
    `pet_logic.py` and `mcp/server.py` both do `from ... import sleep` and
    call `sleep.is_asleep(...)`, so patching the attribute on the shared
    `pet_care.sleep` module object here covers every caller. Tests that
    specifically exercise sleep behavior override this with their own patch.
    """
    with patch("github_tamagotchi.services.pet_care.sleep.is_asleep", return_value=False):
        yield


# Mock data fixtures for testing


@pytest.fixture
def healthy_repo() -> RepoHealth:
    """Create a healthy repository state."""
    return RepoHealth(
        last_commit_at=datetime.now(UTC) - timedelta(hours=1),
        open_prs_count=0,
        oldest_pr_age_hours=None,
        open_issues_count=0,
        oldest_issue_age_days=None,
        last_ci_success=True,
        has_stale_dependencies=False,
        security_alerts_critical=0,
        security_alerts_high=0,
        security_alerts_medium=0,
        security_alerts_low=0,
    )


@pytest.fixture
def unhealthy_repo() -> RepoHealth:
    """Create an unhealthy repository state."""
    return RepoHealth(
        last_commit_at=datetime.now(UTC) - timedelta(days=10),
        open_prs_count=5,
        oldest_pr_age_hours=100,
        open_issues_count=20,
        oldest_issue_age_days=30,
        last_ci_success=False,
        has_stale_dependencies=True,
        security_alerts_critical=0,
        security_alerts_high=0,
        security_alerts_medium=0,
        security_alerts_low=0,
    )


@pytest.fixture
def mock_commit_response() -> list[dict[str, Any]]:
    """Mock GitHub commits API response."""
    return [{"sha": "abc123", "commit": {"committer": {"date": "2025-01-10T12:00:00Z"}}}]


@pytest.fixture
def mock_prs_response() -> list[dict[str, Any]]:
    """Mock GitHub pull requests API response."""
    return [
        {
            "id": 1,
            "number": 1,
            "title": "Test PR",
            "created_at": "2025-01-08T12:00:00Z",
            "state": "open",
        },
        {
            "id": 2,
            "number": 2,
            "title": "Another PR",
            "created_at": "2025-01-09T12:00:00Z",
            "state": "open",
        },
    ]


@pytest.fixture
def mock_issues_response() -> list[dict[str, Any]]:
    """Mock GitHub issues API response."""
    return [
        {
            "id": 1,
            "number": 1,
            "title": "Bug report",
            "created_at": "2025-01-05T12:00:00Z",
            "state": "open",
        },
        {
            "id": 2,
            "number": 2,
            "title": "Feature request",
            "created_at": "2025-01-07T12:00:00Z",
            "state": "open",
        },
        {
            "id": 3,
            "number": 3,
            "title": "PR as issue",
            "created_at": "2025-01-09T12:00:00Z",
            "state": "open",
            "pull_request": {"url": "https://..."},  # Should be filtered out
        },
    ]


@pytest.fixture
def mock_repo_response() -> dict[str, Any]:
    """Mock GitHub repository API response."""
    return {
        "id": 12345,
        "name": "test-repo",
        "full_name": "owner/test-repo",
        "default_branch": "main",
    }


@pytest.fixture
def mock_status_response_success() -> dict[str, Any]:
    """Mock GitHub status API response for successful CI."""
    return {
        "state": "success",
        "statuses": [],
    }


@pytest.fixture
def mock_status_response_failure() -> dict[str, Any]:
    """Mock GitHub status API response for failed CI."""
    return {
        "state": "failure",
        "statuses": [],
    }


@pytest.fixture
def mock_security_alerts_response() -> list[dict[str, Any]]:
    """Mock GitHub Dependabot alerts API response with mixed severities."""
    return [
        {
            "number": 1,
            "state": "open",
            "security_advisory": {"severity": "critical", "summary": "Critical vuln"},
        },
        {
            "number": 2,
            "state": "open",
            "security_advisory": {"severity": "high", "summary": "High vuln"},
        },
        {
            "number": 3,
            "state": "open",
            "security_advisory": {"severity": "medium", "summary": "Medium vuln"},
        },
        {
            "number": 4,
            "state": "open",
            "security_advisory": {"severity": "low", "summary": "Low vuln"},
        },
    ]


@pytest.fixture
def mock_security_alerts_empty() -> list[dict[str, Any]]:
    """Mock GitHub Dependabot alerts API response with no alerts."""
    return []
