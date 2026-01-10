"""Test fixtures and configuration."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


# Test-specific Pydantic models (avoid importing production database)
class TestPetCreate(BaseModel):
    repo_owner: str
    repo_name: str
    name: str


class TestPetResponse(BaseModel):
    id: int
    repo_owner: str
    repo_name: str
    name: str
    stage: str
    mood: str
    health: int
    experience: int


class TestHealthResponse(BaseModel):
    status: str
    version: str
    database: str


async def get_test_session() -> AsyncIterator[AsyncSession]:
    """Get a test database session."""
    async with test_session_factory() as session:
        yield session


def create_test_app() -> FastAPI:
    """Create a test FastAPI app without the production dependencies."""
    from typing import Annotated

    from fastapi import APIRouter

    test_app = FastAPI(title="GitHub Tamagotchi Test")
    test_router = APIRouter(prefix="/api/v1", tags=["pets"])
    db_session_dep = Annotated[AsyncSession, Depends(get_test_session)]

    @test_router.get("/health", response_model=TestHealthResponse)
    async def health_check(session: db_session_dep) -> TestHealthResponse:
        from github_tamagotchi import __version__

        try:
            await session.execute(text("SELECT 1"))
            db_status = "connected"
        except Exception:
            db_status = "disconnected"

        return TestHealthResponse(status="healthy", version=__version__, database=db_status)

    @test_router.post("/pets", response_model=TestPetResponse)
    async def create_pet(pet_data: TestPetCreate, session: db_session_dep) -> Any:
        raise HTTPException(status_code=501, detail="Not implemented yet")

    @test_router.get("/pets/{repo_owner}/{repo_name}", response_model=TestPetResponse)
    async def get_pet(repo_owner: str, repo_name: str, session: db_session_dep) -> Any:
        raise HTTPException(status_code=501, detail="Not implemented yet")

    @test_router.post("/pets/{repo_owner}/{repo_name}/feed")
    async def feed_pet(repo_owner: str, repo_name: str, session: db_session_dep) -> Any:
        raise HTTPException(status_code=501, detail="Not implemented yet")

    test_app.include_router(test_router)

    @test_app.get("/")
    async def root() -> dict[str, str]:
        from github_tamagotchi import __version__

        return {
            "name": "GitHub Tamagotchi",
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


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Create test client with test database."""
    test_app = create_test_app()

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="session", autouse=True)
async def cleanup_test_engine() -> AsyncIterator[None]:
    """Cleanup test engine after all tests."""
    yield
    await test_engine.dispose()
