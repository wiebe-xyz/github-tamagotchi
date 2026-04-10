"""Tests for pet naming and customization endpoints."""

from collections.abc import AsyncIterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from github_tamagotchi.api.auth import _create_jwt, auth_router
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base
from github_tamagotchi.models.user import User
from tests.conftest import get_test_session, test_engine, test_session_factory


def create_naming_test_app() -> FastAPI:
    app = FastAPI(title="Naming Test")
    app.include_router(router)
    app.include_router(auth_router)
    app.dependency_overrides[get_session] = get_test_session
    return app


@pytest.fixture
async def anon_client() -> AsyncIterator[AsyncClient]:
    """Unauthenticated client with fresh DB."""
    app = create_naming_test_app()
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
    """Authenticated client that is the pet owner."""
    app = create_naming_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        user = User(github_id=91001, github_login="petowner", github_avatar_url=None)
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
    """Authenticated client that does NOT own the pet."""
    app = create_naming_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        user = User(github_id=91002, github_login="stranger", github_avatar_url=None)
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


async def _create_pet(client: AsyncClient, owner_user_id: int | None = None) -> None:
    with patch(
        "github_tamagotchi.api.routes.get_image_provider",
        side_effect=ValueError("no provider"),
    ):
        resp = await client.post(
            "/api/v1/pets",
            json={"repo_owner": "testowner", "repo_name": "testrepo", "name": "Fluffy"},
        )
    assert resp.status_code == 201


class TestAutoNaming:
    """Tests for automatic name generation on pet creation."""

    async def test_create_pet_without_name_gets_auto_name(
        self, anon_client: AsyncClient
    ) -> None:
        """Creating a pet without a name generates one from the repo name."""
        with patch(
            "github_tamagotchi.api.routes.get_image_provider",
            side_effect=ValueError("no provider"),
        ):
            resp = await anon_client.post(
                "/api/v1/pets",
                json={"repo_owner": "testowner", "repo_name": "cool-project"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"]  # non-empty
        assert len(data["name"]) <= 20

    async def test_create_pet_with_explicit_name_uses_it(
        self, anon_client: AsyncClient
    ) -> None:
        """An explicit name overrides auto-generation."""
        with patch(
            "github_tamagotchi.api.routes.get_image_provider",
            side_effect=ValueError("no provider"),
        ):
            resp = await anon_client.post(
                "/api/v1/pets",
                json={"repo_owner": "testowner", "repo_name": "cool-project", "name": "Pixel"},
            )
        assert resp.status_code == 201
        assert resp.json()["name"] == "Pixel"

    async def test_create_pet_with_invalid_name_fails(
        self, anon_client: AsyncClient
    ) -> None:
        """Invalid name (special chars) is rejected."""
        with patch(
            "github_tamagotchi.api.routes.get_image_provider",
            side_effect=ValueError("no provider"),
        ):
            resp = await anon_client.post(
                "/api/v1/pets",
                json={"repo_owner": "testowner", "repo_name": "myrepo", "name": "Bad@Name!"},
            )
        assert resp.status_code == 422

    async def test_create_pet_with_profane_name_fails(
        self, anon_client: AsyncClient
    ) -> None:
        """Profane name is rejected."""
        with patch(
            "github_tamagotchi.api.routes.get_image_provider",
            side_effect=ValueError("no provider"),
        ):
            resp = await anon_client.post(
                "/api/v1/pets",
                json={"repo_owner": "testowner", "repo_name": "myrepo", "name": "shit"},
            )
        assert resp.status_code == 422

    async def test_create_pet_with_name_too_long_fails(
        self, anon_client: AsyncClient
    ) -> None:
        """Name longer than 20 chars is rejected."""
        with patch(
            "github_tamagotchi.api.routes.get_image_provider",
            side_effect=ValueError("no provider"),
        ):
            resp = await anon_client.post(
                "/api/v1/pets",
                json={"repo_owner": "testowner", "repo_name": "myrepo", "name": "A" * 21},
            )
        assert resp.status_code == 422


class TestRenamePet:
    """Tests for PUT /api/v1/pets/{owner}/{repo}/name."""

    async def test_owner_can_rename(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Pet owner can successfully rename their pet."""
        client, _ = owner_client
        await _create_pet(client)

        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/name",
            json={"name": "Sprout"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Sprout"

    async def test_rename_reflected_in_get(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Renamed pet shows new name on subsequent GET."""
        client, _ = owner_client
        await _create_pet(client)
        await client.put(
            "/api/v1/pets/testowner/testrepo/name",
            json={"name": "NewName"},
        )
        resp = await client.get("/api/v1/pets/testowner/testrepo")
        assert resp.json()["name"] == "NewName"

    async def test_non_owner_cannot_rename(
        self, owner_client: tuple[AsyncClient, User], other_client: tuple[AsyncClient, User]
    ) -> None:
        """Non-owner receives 403 when trying to rename."""
        owner, _ = owner_client
        await _create_pet(owner)

        stranger, _ = other_client
        resp = await stranger.put(
            "/api/v1/pets/testowner/testrepo/name",
            json={"name": "Hijacked"},
        )
        assert resp.status_code == 403

    async def test_unauthenticated_rename_fails(
        self, anon_client: AsyncClient, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Unauthenticated requests are rejected."""
        owner, _ = owner_client
        await _create_pet(owner)

        resp = await anon_client.put(
            "/api/v1/pets/testowner/testrepo/name",
            json={"name": "Hacker"},
        )
        assert resp.status_code in (401, 403)

    async def test_rename_pet_not_found(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        resp = await client.put(
            "/api/v1/pets/nobody/norepo/name",
            json={"name": "Ghost"},
        )
        assert resp.status_code == 404

    async def test_rename_invalid_name(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        await _create_pet(client)
        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/name",
            json={"name": "Bad!Name"},
        )
        assert resp.status_code == 422

    async def test_rename_profane_name(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        await _create_pet(client)
        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/name",
            json={"name": "fuck"},
        )
        assert resp.status_code == 422

    async def test_rename_too_long(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        await _create_pet(client)
        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/name",
            json={"name": "A" * 21},
        )
        assert resp.status_code == 422


class TestBadgeStyleUpdate:
    """Tests for PUT /api/v1/pets/{owner}/{repo}/badge-style."""

    async def test_owner_can_set_minimal(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        await _create_pet(client)
        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/badge-style",
            json={"badge_style": "minimal"},
        )
        assert resp.status_code == 200
        assert resp.json()["badge_style"] == "minimal"

    async def test_owner_can_set_maintained(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        await _create_pet(client)
        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/badge-style",
            json={"badge_style": "maintained"},
        )
        assert resp.status_code == 200
        assert resp.json()["badge_style"] == "maintained"

    async def test_owner_can_set_playful(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        await _create_pet(client)
        # First switch to minimal, then back to playful
        await client.put(
            "/api/v1/pets/testowner/testrepo/badge-style",
            json={"badge_style": "minimal"},
        )
        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/badge-style",
            json={"badge_style": "playful"},
        )
        assert resp.status_code == 200
        assert resp.json()["badge_style"] == "playful"

    async def test_invalid_badge_style_rejected(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        client, _ = owner_client
        await _create_pet(client)
        resp = await client.put(
            "/api/v1/pets/testowner/testrepo/badge-style",
            json={"badge_style": "sparkly"},
        )
        assert resp.status_code == 422

    async def test_non_owner_cannot_change_badge_style(
        self, owner_client: tuple[AsyncClient, User], other_client: tuple[AsyncClient, User]
    ) -> None:
        owner, _ = owner_client
        await _create_pet(owner)

        stranger, _ = other_client
        resp = await stranger.put(
            "/api/v1/pets/testowner/testrepo/badge-style",
            json={"badge_style": "minimal"},
        )
        assert resp.status_code == 403

    async def test_badge_svg_reflects_style(
        self, owner_client: tuple[AsyncClient, User]
    ) -> None:
        """Badge SVG content changes when badge style changes."""
        client, _ = owner_client
        await _create_pet(client)

        svg_playful = (await client.get("/api/v1/pets/testowner/testrepo/badge.svg")).text

        await client.put(
            "/api/v1/pets/testowner/testrepo/badge-style",
            json={"badge_style": "maintained"},
        )
        svg_maintained = (await client.get("/api/v1/pets/testowner/testrepo/badge.svg")).text

        # Maintained badge has no gradient background — sanity check
        assert svg_maintained != svg_playful


class TestListBadgeStyles:
    """Tests for GET /api/v1/badge-styles."""

    async def test_returns_list(self, anon_client: AsyncClient) -> None:
        resp = await anon_client.get("/api/v1/badge-styles")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert "playful" in data
        assert "minimal" in data
        assert "maintained" in data
