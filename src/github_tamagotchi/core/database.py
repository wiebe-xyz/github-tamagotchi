"""Database configuration and session management."""

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi.core.config import settings


def _get_engine_kwargs() -> dict[str, Any]:
    """Get engine kwargs based on database type."""
    kwargs: dict[str, Any] = {"echo": settings.debug}

    # SQLite doesn't support connection pooling options
    if not settings.database_url.startswith("sqlite"):
        kwargs.update(
            {
                "pool_size": 5,
                "max_overflow": 10,
                "pool_pre_ping": True,
            }
        )

    return kwargs


engine = create_async_engine(settings.database_url, **_get_engine_kwargs())

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Get a database session."""
    async with async_session_factory() as session:
        yield session


async def check_database_connection() -> bool:
    """Check if database is reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_database() -> None:
    """Close database connections."""
    await engine.dispose()
