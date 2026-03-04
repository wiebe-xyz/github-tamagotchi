"""E2E test fixtures - full application lifecycle testing."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

e2e_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
e2e_session_factory = async_sessionmaker(
    e2e_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_e2e_session() -> AsyncIterator[AsyncSession]:
    """Get an E2E test database session."""
    async with e2e_session_factory() as session:
        yield session


@pytest.fixture
async def e2e_client() -> AsyncIterator[AsyncClient]:
    """Create an E2E test client with a fresh database per test."""
    from fastapi import FastAPI

    app = FastAPI(title="GitHub Tamagotchi E2E")
    app.include_router(router)
    app.dependency_overrides[get_session] = get_e2e_session

    async with e2e_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    async with e2e_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="session", autouse=True)
async def cleanup_e2e_engine() -> AsyncIterator[None]:
    """Cleanup E2E engine after all tests."""
    yield
    await e2e_engine.dispose()
