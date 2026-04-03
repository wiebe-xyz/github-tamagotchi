"""API tests for auth routes."""

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


def create_auth_test_app() -> FastAPI:
    """Create a test app with both API and auth routes."""
    app = FastAPI(title="Auth Test")
    app.include_router(router)
    app.include_router(auth_router)
    app.dependency_overrides[get_session] = get_test_session
    return app


@pytest.fixture
async def auth_client() -> AsyncIterator[AsyncClient]:
    """AsyncClient with auth routes."""
    app = create_auth_test_app()
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
async def test_user() -> AsyncIterator[User]:
    """Create a test user in the database."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with test_session_factory() as session:
        user = User(
            github_id=12345,
            github_login="testuser",
            github_avatar_url="https://example.com/avatar.png",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        yield user
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


class TestLoginEndpoint:
    """Tests for GET /auth/github."""

    async def test_redirects_to_github_when_configured(self, auth_client: AsyncClient) -> None:
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = "test-client-id"
            mock_settings.oauth_redirect_uri = "http://test/auth/callback"
            response = await auth_client.get("/auth/github")
        assert response.status_code == 307
        location = response.headers["location"]
        assert "github.com/login/oauth/authorize" in location
        assert "client_id=test-client-id" in location

    async def test_returns_503_when_not_configured(self, auth_client: AsyncClient) -> None:
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = None
            response = await auth_client.get("/auth/github")
        assert response.status_code == 503


class TestCallbackEndpoint:
    """Tests for GET /auth/callback."""

    async def test_returns_400_without_code(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get("/auth/callback")
        assert response.status_code == 400

    async def test_returns_400_with_invalid_state(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get("/auth/callback?code=test&state=invalid")
        assert response.status_code == 400


class TestMeEndpoint:
    """Tests for GET /auth/me."""

    async def test_returns_401_without_token(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get("/auth/me")
        assert response.status_code == 401

    async def test_returns_user_with_valid_token(self, test_user: User) -> None:
        app = create_auth_test_app()
        token = _create_jwt(test_user.id)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={"session_token": token},
        ) as client:
            response = await client.get("/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["github_login"] == "testuser"
        assert data["github_id"] == 12345

    async def test_returns_401_with_invalid_token(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get(
            "/auth/me",
            cookies={"session_token": "invalid-token"},
        )
        assert response.status_code == 401


class TestLogoutEndpoint:
    """Tests for POST /auth/logout."""

    async def test_clears_session_cookie(self, auth_client: AsyncClient) -> None:
        response = await auth_client.post("/auth/logout")
        assert response.status_code == 200
        set_cookie = response.headers.get("set-cookie", "")
        assert "session_token" in set_cookie


class TestMyPetsEndpoint:
    """Tests for GET /api/v1/me/pets."""

    async def test_returns_401_without_auth(self, auth_client: AsyncClient) -> None:
        response = await auth_client.get("/api/v1/me/pets")
        assert response.status_code == 401

    async def test_returns_empty_list_for_new_user(self, test_user: User) -> None:
        app = create_auth_test_app()
        token = _create_jwt(test_user.id)
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={"session_token": token},
        ) as client:
            response = await client.get("/api/v1/me/pets")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
