"""Tests for admin HTML pages."""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from github_tamagotchi.api.auth import _create_jwt
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.models.user import User
from tests.conftest import test_session_factory


@contextmanager
def _as_admin(login: str) -> Iterator[None]:
    """Patch settings so the given login is treated as admin."""
    with patch(
        "github_tamagotchi.api.auth.settings.admin_github_logins",
        new=[login],
    ), patch(
        "github_tamagotchi.main.settings.admin_github_logins",
        new=[login],
    ):
        yield


def _create_user(user_id: int, github_login: str) -> str:
    async def _setup() -> str:
        async with test_session_factory() as session:
            user = User(
                id=user_id,
                github_id=user_id * 1000,
                github_login=github_login,
                github_avatar_url=None,
            )
            session.add(user)
            await session.commit()
        return _create_jwt(user_id=user_id)

    return asyncio.run(_setup())


def _create_pet(
    repo_owner: str = "adminorg",
    repo_name: str = "adminrepo",
    name: str = "AdminPet",
    user_id: int | None = None,
) -> None:
    async def _setup() -> None:
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name=name,
                stage=PetStage.BABY.value,
                mood=PetMood.HAPPY.value,
                health=80,
                user_id=user_id,
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_setup())


class TestAdminOverviewPage:
    """Tests for /admin HTML page."""

    def test_unauthenticated_gets_401(self, client: TestClient) -> None:
        response = client.get("/admin", follow_redirects=False)
        assert response.status_code in (401, 302)

    def test_non_admin_gets_403(self, client: TestClient) -> None:
        token = _create_user(user_id=351, github_login="notadmin351")
        response = client.get("/admin", cookies={"session_token": token})
        assert response.status_code == 403

    def test_admin_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=300, github_login="adminlogin300")
        with _as_admin("adminlogin300"):
            response = client.get("/admin", cookies={"session_token": token})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_admin_shows_overview_content(self, client: TestClient) -> None:
        token = _create_user(user_id=301, github_login="adminlogin301")
        with _as_admin("adminlogin301"):
            response = client.get("/admin", cookies={"session_token": token})
        assert "Admin" in response.text
        assert "Users" in response.text
        assert "Pets" in response.text


class TestAdminPetsPage:
    """Tests for /admin/pets HTML page."""

    def test_admin_pets_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=310, github_login="adminlogin310")
        with _as_admin("adminlogin310"):
            response = client.get("/admin/pets", cookies={"session_token": token})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_non_admin_gets_403(self, client: TestClient) -> None:
        token = _create_user(user_id=352, github_login="notadmin352")
        response = client.get("/admin/pets", cookies={"session_token": token})
        assert response.status_code == 403

    def test_shows_pet_in_list(self, client: TestClient) -> None:
        token = _create_user(user_id=311, github_login="adminlogin311")
        _create_pet(repo_owner="adminpetowner", repo_name="adminpetrepo", name="AdminListedPet")
        with _as_admin("adminlogin311"):
            response = client.get("/admin/pets", cookies={"session_token": token})
        assert "AdminListedPet" in response.text


class TestAdminJobsPage:
    """Tests for /admin/jobs HTML page."""

    def test_admin_jobs_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=320, github_login="adminlogin320")
        with _as_admin("adminlogin320"):
            response = client.get("/admin/jobs", cookies={"session_token": token})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_non_admin_gets_403(self, client: TestClient) -> None:
        token = _create_user(user_id=353, github_login="notadmin353")
        response = client.get("/admin/jobs", cookies={"session_token": token})
        assert response.status_code == 403


class TestAdminAchievementsPage:
    """Tests for /admin/achievements HTML page."""

    def test_admin_achievements_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=330, github_login="adminlogin330")
        with _as_admin("adminlogin330"):
            response = client.get("/admin/achievements", cookies={"session_token": token})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_non_admin_gets_403(self, client: TestClient) -> None:
        token = _create_user(user_id=354, github_login="notadmin354")
        response = client.get("/admin/achievements", cookies={"session_token": token})
        assert response.status_code == 403

    def test_shows_achievements_content(self, client: TestClient) -> None:
        token = _create_user(user_id=331, github_login="adminlogin331")
        with _as_admin("adminlogin331"):
            response = client.get("/admin/achievements", cookies={"session_token": token})
        assert "Achievement" in response.text


class TestAdminWebhooksPage:
    """Tests for /admin/webhooks HTML page."""

    def test_admin_webhooks_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=340, github_login="adminlogin340")
        with _as_admin("adminlogin340"):
            response = client.get("/admin/webhooks", cookies={"session_token": token})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_non_admin_gets_403(self, client: TestClient) -> None:
        token = _create_user(user_id=355, github_login="notadmin355")
        response = client.get("/admin/webhooks", cookies={"session_token": token})
        assert response.status_code == 403


class TestAdminSpritesPage:
    """Tests for /admin/sprites HTML page and regenerate endpoint."""

    def test_admin_sprites_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=360, github_login="adminlogin360")
        with _as_admin("adminlogin360"):
            response = client.get("/admin/sprites", cookies={"session_token": token})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_non_admin_gets_403(self, client: TestClient) -> None:
        token = _create_user(user_id=361, github_login="notadmin361")
        response = client.get("/admin/sprites", cookies={"session_token": token})
        assert response.status_code == 403

    def test_shows_all_stages(self, client: TestClient) -> None:
        token = _create_user(user_id=362, github_login="adminlogin362")
        with _as_admin("adminlogin362"):
            response = client.get("/admin/sprites", cookies={"session_token": token})
        for stage in PetStage:
            assert stage.value.capitalize() in response.text

    def test_shows_sprites_nav_link(self, client: TestClient) -> None:
        token = _create_user(user_id=363, github_login="adminlogin363")
        with _as_admin("adminlogin363"):
            response = client.get("/admin/sprites", cookies={"session_token": token})
        assert "/admin/sprites" in response.text

    def test_regenerate_unknown_stage_returns_400(self, client: TestClient) -> None:
        token = _create_user(user_id=364, github_login="adminlogin364")
        with _as_admin("adminlogin364"):
            response = client.post(
                "/admin/sprites/regenerate",
                json={"stage": "notastage"},
                cookies={"session_token": token},
            )
        assert response.status_code == 400

    def test_regenerate_valid_stage_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=365, github_login="adminlogin365")
        with _as_admin("adminlogin365"):
            response = client.post(
                "/admin/sprites/regenerate",
                json={"stage": "egg"},
                cookies={"session_token": token},
            )
        assert response.status_code == 200
        data = response.json()
        assert "queued" in data
        assert data["stage"] == "egg"

    def test_regenerate_all_stages_returns_200(self, client: TestClient) -> None:
        token = _create_user(user_id=366, github_login="adminlogin366")
        with _as_admin("adminlogin366"):
            response = client.post(
                "/admin/sprites/regenerate",
                json={"stage": "all"},
                cookies={"session_token": token},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["stage"] == "all"

    def test_regenerate_queues_jobs_for_pets(self, client: TestClient) -> None:
        token = _create_user(user_id=367, github_login="adminlogin367")
        _create_pet(repo_owner="spriteowner", repo_name="spriterepo", name="SpritePet")
        with _as_admin("adminlogin367"):
            response = client.post(
                "/admin/sprites/regenerate",
                json={"stage": "baby"},
                cookies={"session_token": token},
            )
        assert response.status_code == 200
        assert response.json()["queued"] >= 1

    def test_regenerate_non_admin_gets_403(self, client: TestClient) -> None:
        token = _create_user(user_id=368, github_login="notadmin368")
        response = client.post(
            "/admin/sprites/regenerate",
            json={"stage": "egg"},
            cookies={"session_token": token},
        )
        assert response.status_code == 403
