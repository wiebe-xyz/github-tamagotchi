"""Test fixtures and configuration."""

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
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
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

    # Include the production API router
    test_app.include_router(router)

    # Override the database session dependency
    test_app.dependency_overrides[get_session] = get_test_session

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


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Create sync test client for production app testing (with templates/static)."""
    # Mock run_worker to be a coroutine that returns immediately when stop is set
    async def mock_run_worker(
        session_factory: object,
        stop_event: asyncio.Event | None = None,
        poll_interval: float | None = None,
    ) -> None:
        # Just wait for stop event immediately
        if stop_event:
            await stop_event.wait()

    # Patch the scheduler and image queue worker to prevent them from starting
    with (
        patch("github_tamagotchi.main.scheduler") as mock_scheduler,
        patch(
            "github_tamagotchi.services.image_queue.run_worker",
            side_effect=mock_run_worker,
        ),
    ):
        mock_scheduler.start = lambda: None
        mock_scheduler.shutdown = lambda: None
        mock_scheduler.add_job = lambda *args, **kwargs: None

        # Import after patching to get the patched version
        from github_tamagotchi.main import app

        # Override database dependency
        app.dependency_overrides[get_session] = get_test_session

        with TestClient(app) as tc:
            yield tc

        # Clean up overrides
        app.dependency_overrides.clear()


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_engine() -> AsyncIterator[None]:
    """Cleanup test engine after all tests."""
    yield
    await test_engine.dispose()


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
