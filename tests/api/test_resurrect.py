"""Tests for the pet resurrection endpoint."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from github_tamagotchi.api.auth import _create_jwt, auth_router
from github_tamagotchi.api.exception_handlers import register_exception_handlers
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base, PetMood, PetStage
from github_tamagotchi.models.user import User
from tests.conftest import get_test_session, test_engine, test_session_factory


def create_resurrect_test_app() -> FastAPI:
    """Create a test app with API and auth routes."""
    app = FastAPI(title="Resurrect Test")
    app.include_router(router)
    app.include_router(auth_router)
    app.dependency_overrides[get_session] = get_test_session
    register_exception_handlers(app)
    return app


@pytest.fixture
async def resurrect_client() -> AsyncIterator[AsyncClient]:
    """AsyncClient with a fresh in-memory database (no auth)."""
    app = create_resurrect_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        yield client
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def owner_client() -> AsyncIterator[tuple[AsyncClient, User]]:
    """AsyncClient authenticated as the pet owner."""
    app = create_resurrect_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        user = User(
            github_id=77001,
            github_login="petowner",
            github_avatar_url=None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    token = _create_jwt(user.id)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_token": token},
    ) as client:
        yield client, user

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def other_client() -> AsyncIterator[tuple[AsyncClient, User]]:
    """AsyncClient authenticated as a different user (non-owner)."""
    app = create_resurrect_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        user = User(
            github_id=77002,
            github_login="nottheowner",
            github_avatar_url=None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    token = _create_jwt(user.id)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_token": token},
    ) as client:
        yield client, user

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _create_pet_for_user(
    client: AsyncClient, owner: str = "owner", repo: str = "repo"
) -> None:
    """Helper: create a pet via API (no image provider)."""
    with patch(
        "github_tamagotchi.api.routes.get_image_provider",
        side_effect=ValueError("no provider"),
    ):
        resp = await client.post(
            "/api/v1/pets",
            json={"repo_owner": owner, "repo_name": repo, "name": "GhostPet"},
        )
    assert resp.status_code == 201


async def _mark_pet_dead(
    died_at: datetime,
    owner: str = "owner",
    repo: str = "repo",
) -> None:
    """Helper: directly update a pet in the DB to be dead with given died_at."""
    from sqlalchemy import update as sa_update

    from github_tamagotchi.models.pet import Pet

    async with test_session_factory() as session:
        await session.execute(
            sa_update(Pet)
            .where(Pet.repo_owner == owner, Pet.repo_name == repo)
            .values(
                is_dead=True,
                died_at=died_at,
                cause_of_death="neglect",
                health=0,
            )
        )
        await session.commit()


async def _assign_pet_owner(user_id: int, owner: str = "owner", repo: str = "repo") -> None:
    """Helper: assign a pet to a specific user in the DB."""
    from sqlalchemy import update as sa_update

    from github_tamagotchi.models.pet import Pet

    async with test_session_factory() as session:
        await session.execute(
            sa_update(Pet)
            .where(Pet.repo_owner == owner, Pet.repo_name == repo)
            .values(user_id=user_id)
        )
        await session.commit()


class TestResurrectEndpoint:
    """Tests for POST /api/v1/pets/{owner}/{repo}/resurrect."""

    async def test_resurrect_requires_auth(self, resurrect_client: AsyncClient) -> None:
        """Calling resurrect without auth should return 401."""
        resp = await resurrect_client.post("/api/v1/pets/owner/repo/resurrect")
        assert resp.status_code == 401

    async def test_resurrect_living_pet_returns_400(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Trying to resurrect a living pet should return 400."""
        client, user = owner_client
        await _create_pet_for_user(client)
        await _assign_pet_owner(user.id)

        resp = await client.post("/api/v1/pets/owner/repo/resurrect")
        assert resp.status_code == 400
        assert "not dead" in resp.json()["detail"]

    async def test_resurrect_within_mourning_period_returns_400(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Resurrecting within 7 days of death should return 400 with days remaining."""
        client, user = owner_client
        await _create_pet_for_user(client)
        await _assign_pet_owner(user.id)

        # Pet died 3 days ago — 4 days still remaining
        died_at = datetime.now(UTC) - timedelta(days=3)
        await _mark_pet_dead(died_at)

        resp = await client.post("/api/v1/pets/owner/repo/resurrect")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "must rest" in detail
        assert "4" in detail  # 4 days remaining

    async def test_resurrect_days_remaining_singular(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """When exactly 1 day remains the message should say 'day' not 'days'."""
        client, user = owner_client
        await _create_pet_for_user(client)
        await _assign_pet_owner(user.id)

        # Pet died 6 days ago — 1 day still remaining
        died_at = datetime.now(UTC) - timedelta(days=6)
        await _mark_pet_dead(died_at)

        resp = await client.post("/api/v1/pets/owner/repo/resurrect")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "1 more day before" in detail

    async def test_resurrect_after_mourning_period_succeeds(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Resurrecting after 7 days should succeed and reset pet state."""
        client, user = owner_client
        await _create_pet_for_user(client)
        await _assign_pet_owner(user.id)

        # Pet died 8 days ago — mourning period over
        died_at = datetime.now(UTC) - timedelta(days=8)
        await _mark_pet_dead(died_at)

        with patch(
            "github_tamagotchi.api.routes.get_image_provider",
            side_effect=ValueError("no provider"),
        ):
            resp = await client.post("/api/v1/pets/owner/repo/resurrect")

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_dead"] is False
        assert data["died_at"] is None
        assert data["cause_of_death"] is None
        assert data["stage"] == PetStage.EGG.value
        assert data["health"] == 60
        assert data["experience"] == 0
        assert data["mood"] == PetMood.CONTENT.value
        assert data["generation"] == 2

    async def test_resurrect_increments_generation(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Each resurrection should increment the generation counter."""
        client, user = owner_client
        await _create_pet_for_user(client)
        await _assign_pet_owner(user.id)

        # Start from gen 1, die and resurrect
        died_at = datetime.now(UTC) - timedelta(days=8)
        await _mark_pet_dead(died_at)

        with patch(
            "github_tamagotchi.api.routes.get_image_provider",
            side_effect=ValueError("no provider"),
        ):
            resp = await client.post("/api/v1/pets/owner/repo/resurrect")
        assert resp.status_code == 200
        assert resp.json()["generation"] == 2

    async def test_resurrect_enqueues_image_job_when_provider_configured(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """On successful resurrection, an EGG-stage image job should be enqueued."""
        client, user = owner_client
        await _create_pet_for_user(client)
        await _assign_pet_owner(user.id)

        died_at = datetime.now(UTC) - timedelta(days=8)
        await _mark_pet_dead(died_at)

        mock_job = object()
        with (
            patch(
                "github_tamagotchi.api.routes.get_image_provider",
                return_value=object(),
            ),
            patch(
                "github_tamagotchi.api.routes.image_queue.create_job",
                new_callable=AsyncMock,
                return_value=mock_job,
            ) as mock_create_job,
        ):
            resp = await client.post("/api/v1/pets/owner/repo/resurrect")

        assert resp.status_code == 200
        mock_create_job.assert_called_once()
        call_args = mock_create_job.call_args
        # Third positional arg or kwarg should be the EGG stage
        stage_arg = (
            call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("stage")
        )
        assert stage_arg == PetStage.EGG.value

    async def test_non_owner_cannot_resurrect(
        self,
        owner_client: tuple[AsyncClient, User],
        other_client: tuple[AsyncClient, User],
    ) -> None:
        """A user who does not own the pet should receive 403."""
        owner, owner_user = owner_client
        stranger, _stranger_user = other_client

        await _create_pet_for_user(owner)
        await _assign_pet_owner(owner_user.id)

        died_at = datetime.now(UTC) - timedelta(days=8)
        await _mark_pet_dead(died_at)

        resp = await stranger.post("/api/v1/pets/owner/repo/resurrect")
        assert resp.status_code == 403
        assert "do not own" in resp.json()["detail"]

    async def test_resurrect_pet_not_found(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Resurrecting a non-existent pet should return 404."""
        client, _user = owner_client
        resp = await client.post("/api/v1/pets/nobody/nopet/resurrect")
        assert resp.status_code == 404
