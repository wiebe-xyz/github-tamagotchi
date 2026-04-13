"""E2E test fixtures: full app with in-memory SQLite and mocked externals."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi.api.exception_handlers import register_exception_handlers
from github_tamagotchi.api.health import health_router
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base, Pet, PetMood, PetStage
from github_tamagotchi.models.user import User  # noqa: F401

E2E_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

e2e_engine = create_async_engine(E2E_DATABASE_URL, echo=False)
e2e_session_factory = async_sessionmaker(e2e_engine, class_=AsyncSession, expire_on_commit=False)


async def get_e2e_session() -> AsyncIterator[AsyncSession]:
    """Provide an E2E database session."""
    async with e2e_session_factory() as session:
        yield session


@asynccontextmanager
async def e2e_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """E2E lifespan: no scheduler, no external services."""
    yield


def create_e2e_app() -> FastAPI:
    """Create E2E test app with DB but no external services."""
    app = FastAPI(title="GitHub Tamagotchi E2E", lifespan=e2e_lifespan)
    app.include_router(router)
    app.include_router(health_router)
    app.dependency_overrides[get_session] = get_e2e_session
    register_exception_handlers(app)
    return app


@pytest.fixture
async def e2e_db() -> AsyncIterator[AsyncSession]:
    """Set up E2E database tables and provide a session."""
    async with e2e_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with e2e_session_factory() as session:
        yield session

    async with e2e_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def e2e_client(e2e_db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """AsyncClient wired to the E2E app with a live database."""
    app = create_e2e_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://e2e",
    ) as client:
        yield client


@pytest.fixture
async def sample_pet(e2e_db: AsyncSession) -> Pet:
    """Insert a sample pet and return it."""
    pet = Pet(
        repo_owner="testowner",
        repo_name="testrepo",
        name="TestPet",
        stage=PetStage.EGG.value,
        mood=PetMood.CONTENT.value,
        health=100,
        experience=0,
    )
    e2e_db.add(pet)
    await e2e_db.commit()
    await e2e_db.refresh(pet)
    return pet


def mock_github_repo(
    owner: str,
    repo: str,
    *,
    commit_age_hours: int = 1,
    prs: list[dict[str, object]] | None = None,
    issues: list[dict[str, object]] | None = None,
    ci_state: str = "success",
) -> None:
    """Register respx mocks for a GitHub repository with configurable state."""
    recent = (datetime.now(UTC) - timedelta(hours=commit_age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits").mock(
        return_value=httpx.Response(
            200, json=[{"sha": "abc", "commit": {"committer": {"date": recent}}}]
        )
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/pulls").mock(
        return_value=httpx.Response(200, json=prs or [])
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/issues").mock(
        return_value=httpx.Response(200, json=issues or [])
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=httpx.Response(200, json={"default_branch": "main"})
    )
    respx.get(f"https://api.github.com/repos/{owner}/{repo}/commits/main/status").mock(
        return_value=httpx.Response(200, json={"state": ci_state, "statuses": []})
    )
