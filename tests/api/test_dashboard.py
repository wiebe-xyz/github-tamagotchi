"""Tests for the dashboard page."""

import asyncio

from fastapi.testclient import TestClient

from github_tamagotchi.api.auth import _create_jwt
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.models.user import User
from tests.conftest import test_session_factory


def _create_user(user_id: int = 1, github_login: str = "dashuser") -> str:
    async def _setup() -> str:
        async with test_session_factory() as session:
            user = User(
                id=user_id,
                github_id=user_id * 1000,
                github_login=github_login,
                github_avatar_url=f"https://avatars.example.com/{github_login}",
            )
            session.add(user)
            await session.commit()
        return _create_jwt(user_id=user_id)

    return asyncio.run(_setup())


def _create_pet_for_user(
    user_id: int, repo_owner: str = "owner", repo_name: str = "repo", name: str = "Gotchi"
) -> None:
    async def _setup() -> None:
        async with test_session_factory() as session:
            pet = Pet(
                repo_owner=repo_owner,
                repo_name=repo_name,
                name=name,
                user_id=user_id,
                stage=PetStage.BABY.value,
                mood=PetMood.HAPPY.value,
                health=80,
                experience=100,
            )
            session.add(pet)
            await session.commit()

    asyncio.run(_setup())


class TestDashboardUnauthenticated:
    def test_redirects_to_auth(self, client: TestClient) -> None:
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 302
        assert "/auth/github" in response.headers["location"]


class TestDashboardAuthenticated:
    def test_returns_200_when_logged_in(self, client: TestClient) -> None:
        token = _create_user(user_id=10)
        response = client.get("/dashboard", cookies={"session_token": token})
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_shows_username(self, client: TestClient) -> None:
        token = _create_user(user_id=11, github_login="myuser")
        response = client.get("/dashboard", cookies={"session_token": token})
        assert "myuser" in response.text

    def test_shows_empty_state_when_no_pets(self, client: TestClient) -> None:
        token = _create_user(user_id=12)
        response = client.get("/dashboard", cookies={"session_token": token})
        assert "haven't registered any repos yet" in response.text

    def test_shows_pet_card_when_pet_exists(self, client: TestClient) -> None:
        token = _create_user(user_id=13, github_login="petowner")
        _create_pet_for_user(user_id=13, repo_owner="petowner", repo_name="myrepo", name="Buddy")
        response = client.get("/dashboard", cookies={"session_token": token})
        assert "Buddy" in response.text
        assert "petowner/myrepo" in response.text

    def test_shows_health_bar(self, client: TestClient) -> None:
        token = _create_user(user_id=14)
        _create_pet_for_user(user_id=14)
        response = client.get("/dashboard", cookies={"session_token": token})
        assert "Health" in response.text
        assert "80%" in response.text

    def test_shows_register_link(self, client: TestClient) -> None:
        token = _create_user(user_id=15)
        response = client.get("/dashboard", cookies={"session_token": token})
        assert "/register" in response.text

    def test_shows_view_profile_link(self, client: TestClient) -> None:
        token = _create_user(user_id=16, github_login="linkowner")
        _create_pet_for_user(user_id=16, repo_owner="linkowner", repo_name="linkrepo")
        response = client.get("/dashboard", cookies={"session_token": token})
        assert "/pet/linkowner/linkrepo" in response.text
