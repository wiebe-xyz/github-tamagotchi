"""Test fixtures and configuration."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base

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


def create_test_app() -> FastAPI:
    """Create a test FastAPI app without the production lifespan."""
    test_app = FastAPI(title="GitHub Tamagotchi Test")
    test_app.include_router(router)

    @test_app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint."""
        from github_tamagotchi import __version__
        from github_tamagotchi.core.config import settings

        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
        }

    return test_app


@pytest.fixture
async def test_db() -> AsyncIterator[AsyncSession]:
    """Create test database tables and provide a session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_session() -> AsyncIterator[AsyncSession]:
    """Override for get_session dependency in tests."""
    async with test_session_factory() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Create test client with overridden database session."""
    test_app = create_test_app()
    test_app.dependency_overrides[get_session] = override_get_session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
