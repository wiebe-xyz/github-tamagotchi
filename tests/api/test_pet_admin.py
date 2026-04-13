"""Tests for the pet admin panel API endpoints."""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from github_tamagotchi.api.auth import _create_jwt, auth_router
from github_tamagotchi.api.exception_handlers import register_exception_handlers
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base, Pet
from github_tamagotchi.models.user import User
from tests.conftest import get_test_session, test_engine, test_session_factory


def create_admin_test_app() -> FastAPI:
    app = FastAPI(title="Admin Test")
    app.include_router(router)
    app.include_router(auth_router)
    app.dependency_overrides[get_session] = get_test_session
    register_exception_handlers(app)
    return app


@contextmanager
def mock_repo_permission(permission: str = "admin") -> Iterator[None]:
    """Mock both decrypt_token and get_repo_permission for repo admin checks."""
    with patch(
        "github_tamagotchi.api.routes.decrypt_token",
        return_value="fake-token",
    ), patch(
        "github_tamagotchi.api.routes.GitHubService.get_repo_permission",
        new_callable=AsyncMock,
        return_value=permission,
    ):
        yield


@pytest.fixture
async def admin_client() -> AsyncIterator[tuple[AsyncClient, User, Pet]]:
    """Authenticated client with a token, to be used with mock_repo_permission."""
    app = create_admin_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        user = User(
            github_id=99001,
            github_login="repoadmin",
            github_avatar_url=None,
            encrypted_token="fake-encrypted-token",
        )
        session.add(user)
        await session.flush()

        pet = Pet(
            repo_owner="repoadmin",
            repo_name="myrepo",
            name="TestPet",
            user_id=user.id,
        )
        session.add(pet)
        await session.commit()
        await session.refresh(user)
        await session.refresh(pet)

    token = _create_jwt(user.id)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_token": token},
    ) as client:
        yield client, user, pet

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def non_admin_client() -> AsyncIterator[tuple[AsyncClient, Pet]]:
    """Authenticated client whose repo permission will be mocked as non-admin."""
    app = create_admin_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        owner = User(github_id=99002, github_login="petowner", github_avatar_url=None)
        other = User(
            github_id=99003,
            github_login="outsider",
            github_avatar_url=None,
            encrypted_token="fake-encrypted-token",
        )
        session.add(owner)
        session.add(other)
        await session.flush()

        pet = Pet(
            repo_owner="petowner",
            repo_name="myrepo",
            name="TestPet",
            user_id=owner.id,
        )
        session.add(pet)
        await session.commit()
        await session.refresh(other)
        await session.refresh(pet)

    token = _create_jwt(other.id)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_token": token},
    ) as client:
        yield client, pet

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def anon_client() -> AsyncIterator[tuple[AsyncClient, Pet]]:
    """Unauthenticated client with a pet in the database."""
    app = create_admin_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        user = User(github_id=99004, github_login="owner4", github_avatar_url=None)
        session.add(user)
        await session.flush()
        pet = Pet(repo_owner="owner4", repo_name="repo4", name="Pet4", user_id=user.id)
        session.add(pet)
        await session.commit()
        await session.refresh(pet)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, pet

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestGetPetAdmin:
    async def test_returns_settings_for_repo_admin(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            resp = await client.get(f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TestPet"
        assert data["blame_board_enabled"] is True
        assert data["contributor_badges_enabled"] is True
        assert data["leaderboard_opt_out"] is False
        assert data["hungry_after_days"] == 3
        assert data["pr_review_sla_hours"] == 48
        assert data["issue_response_sla_days"] == 7
        assert data["excluded_contributors"] == []

    async def test_rejects_unauthenticated(
        self, anon_client: tuple[AsyncClient, Pet]
    ) -> None:
        client, pet = anon_client
        resp = await client.get(f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin")
        assert resp.status_code == 401

    async def test_rejects_non_repo_admin(
        self, non_admin_client: tuple[AsyncClient, Pet]
    ) -> None:
        client, pet = non_admin_client
        with mock_repo_permission("read"):
            resp = await client.get(f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin")
        assert resp.status_code == 403

    async def test_returns_404_for_missing_pet(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            resp = await client.get("/api/v1/pets/nobody/norepo/admin")
        assert resp.status_code == 404


class TestUpdatePetAdminSettings:
    async def test_rename_pet(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            resp = await client.patch(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/settings",
                json={"name": "NewName"},
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "NewName"

    async def test_toggle_blame_board(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            resp = await client.patch(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/settings",
                json={"blame_board_enabled": False},
            )
        assert resp.status_code == 200
        assert resp.json()["blame_board_enabled"] is False

    async def test_update_thresholds(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            resp = await client.patch(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/settings",
                json={
                    "hungry_after_days": 5,
                    "pr_review_sla_hours": 72,
                    "issue_response_sla_days": 14,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["hungry_after_days"] == 5
        assert data["pr_review_sla_hours"] == 72
        assert data["issue_response_sla_days"] == 14

    async def test_rejects_non_admin(
        self, non_admin_client: tuple[AsyncClient, Pet]
    ) -> None:
        client, pet = non_admin_client
        with mock_repo_permission("read"):
            resp = await client.patch(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/settings",
                json={"name": "Hacked"},
            )
        assert resp.status_code == 403


class TestExcludeContributor:
    async def test_exclude_contributor(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            resp = await client.post(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/contributors/exclude",
                params={"github_login": "bot-user"},
            )
        assert resp.status_code == 201
        assert resp.json()["github_login"] == "bot-user"

    async def test_exclude_idempotent(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            await client.post(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/contributors/exclude",
                params={"github_login": "bot-user"},
            )
            resp = await client.post(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/contributors/exclude",
                params={"github_login": "bot-user"},
            )
        assert resp.status_code == 201

    async def test_appears_in_admin_response(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            await client.post(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/contributors/exclude",
                params={"github_login": "bot-user"},
            )
            resp = await client.get(f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin")
        assert resp.status_code == 200
        logins = [e["github_login"] for e in resp.json()["excluded_contributors"]]
        assert "bot-user" in logins

    async def test_unexclude_removes_entry(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            await client.post(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/contributors/exclude",
                params={"github_login": "bot-user"},
            )
            resp = await client.delete(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/contributors/bot-user/exclude"
            )
            assert resp.status_code == 200

            admin_resp = await client.get(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin"
            )
        logins = [e["github_login"] for e in admin_resp.json()["excluded_contributors"]]
        assert "bot-user" not in logins


class TestResetPet:
    async def test_reset_increments_generation(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        original_gen = pet.generation
        with mock_repo_permission("admin"):
            resp = await client.post(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/reset"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["generation"] == original_gen + 1
        assert data["is_dead"] is False

    async def test_reset_rejects_non_admin(
        self, non_admin_client: tuple[AsyncClient, Pet]
    ) -> None:
        client, pet = non_admin_client
        with mock_repo_permission("read"):
            resp = await client.post(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin/reset"
            )
        assert resp.status_code == 403


class TestDeletePet:
    async def test_delete_pet(
        self, admin_client: tuple[AsyncClient, User, Pet]
    ) -> None:
        client, user, pet = admin_client
        with mock_repo_permission("admin"):
            resp = await client.delete(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin"
            )
        assert resp.status_code == 204

    async def test_delete_rejects_non_admin(
        self, non_admin_client: tuple[AsyncClient, Pet]
    ) -> None:
        client, pet = non_admin_client
        with mock_repo_permission("read"):
            resp = await client.delete(
                f"/api/v1/pets/{pet.repo_owner}/{pet.repo_name}/admin"
            )
        assert resp.status_code == 403
