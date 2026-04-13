"""Tests for the pet comments API endpoints."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from github_tamagotchi.api.auth import _create_jwt, auth_router
from github_tamagotchi.api.exception_handlers import register_exception_handlers
from github_tamagotchi.api.routes import router
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base
from github_tamagotchi.models.user import User
from tests.conftest import get_test_session, test_engine, test_session_factory


def create_comments_test_app() -> FastAPI:
    """Create a test app with API and auth routes."""
    app = FastAPI(title="Comments Test")
    app.include_router(router)
    app.include_router(auth_router)
    app.dependency_overrides[get_session] = get_test_session
    register_exception_handlers(app)
    return app


@pytest.fixture
async def comments_client() -> AsyncIterator[AsyncClient]:
    """AsyncClient with a fresh in-memory database."""
    app = create_comments_test_app()
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
async def authed_client() -> AsyncIterator[tuple[AsyncClient, User]]:
    """AsyncClient with an authenticated user pre-created."""
    app = create_comments_test_app()
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        user = User(
            github_id=99001,
            github_login="commentuser",
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


class TestGetComments:
    """Tests for GET /api/v1/pets/{owner}/{name}/comments."""

    async def test_returns_empty_list_for_new_pet(self, comments_client: AsyncClient) -> None:
        response = await comments_client.get("/api/v1/pets/owner/repo/comments")
        assert response.status_code == 200
        data = response.json()
        assert data == {"comments": []}

    async def test_returns_200_without_auth(self, comments_client: AsyncClient) -> None:
        response = await comments_client.get("/api/v1/pets/some/repo/comments")
        assert response.status_code == 200


class TestPostComment:
    """Tests for POST /api/v1/pets/{owner}/{name}/comments."""

    async def test_requires_authentication(self, comments_client: AsyncClient) -> None:
        response = await comments_client.post(
            "/api/v1/pets/owner/repo/comments",
            json={"body": "hello"},
        )
        assert response.status_code == 401

    async def test_creates_comment_for_authenticated_user(
        self, authed_client: tuple[AsyncClient, User]
    ) -> None:
        client, user = authed_client
        response = await client.post(
            "/api/v1/pets/owner/repo/comments",
            json={"body": "Great repo!"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["body"] == "Great repo!"
        assert data["author_name"] == user.github_login
        assert "id" in data
        assert "created_at" in data

    async def test_comment_appears_in_list(
        self, authed_client: tuple[AsyncClient, User]
    ) -> None:
        client, _user = authed_client
        await client.post(
            "/api/v1/pets/owner/repo/comments",
            json={"body": "First comment"},
        )
        list_resp = await client.get("/api/v1/pets/owner/repo/comments")
        assert list_resp.status_code == 200
        comments = list_resp.json()["comments"]
        assert len(comments) == 1
        assert comments[0]["body"] == "First comment"

    async def test_rejects_empty_body(
        self, authed_client: tuple[AsyncClient, User]
    ) -> None:
        client, _user = authed_client
        response = await client.post(
            "/api/v1/pets/owner/repo/comments",
            json={"body": ""},
        )
        assert response.status_code == 422

    async def test_rejects_body_over_500_chars(
        self, authed_client: tuple[AsyncClient, User]
    ) -> None:
        client, _user = authed_client
        response = await client.post(
            "/api/v1/pets/owner/repo/comments",
            json={"body": "x" * 501},
        )
        assert response.status_code == 422

    async def test_comments_returned_newest_first(
        self, authed_client: tuple[AsyncClient, User]
    ) -> None:
        client, _user = authed_client
        for i in range(3):
            await client.post(
                "/api/v1/pets/owner/repo/comments",
                json={"body": f"Comment {i}"},
            )
        resp = await client.get("/api/v1/pets/owner/repo/comments")
        comments = resp.json()["comments"]
        assert len(comments) == 3
        # newest first — last posted should be first in the list
        assert comments[0]["body"] == "Comment 2"
