"""Unit tests for authentication module."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.api.auth import (
    _cleanup_expired_states,
    _create_jwt,
    _decode_jwt,
    _oauth_states,
    auth_router,
    get_admin_user,
    get_current_user,
    get_optional_user,
)
from github_tamagotchi.core.database import get_session
from github_tamagotchi.models.pet import Base
from github_tamagotchi.models.user import User
from tests.conftest import get_test_session, test_engine


class TestJWT:
    """Tests for JWT creation and validation."""

    def test_create_and_decode_jwt(self) -> None:
        token = _create_jwt(42)
        payload = _decode_jwt(token)
        assert payload["sub"] == "42"
        assert "exp" in payload
        assert "iat" in payload

    def test_expired_jwt_raises(self) -> None:
        # Create a token that is already expired by crafting it directly
        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(minutes=5),
            "iat": datetime.now(UTC) - timedelta(minutes=10),
        }
        token = jwt.encode(payload, "change-me-in-production", algorithm="HS256")
        with pytest.raises(jwt.ExpiredSignatureError):
            _decode_jwt(token)

    def test_invalid_jwt_raises(self) -> None:
        with pytest.raises(jwt.InvalidTokenError):
            _decode_jwt("not-a-valid-token")

    def test_wrong_secret_raises(self) -> None:
        token = _create_jwt(1)
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.jwt_secret_key = "wrong-secret"
            mock_settings.jwt_algorithm = "HS256"
            with pytest.raises(jwt.InvalidSignatureError):
                _decode_jwt(token)


class TestOAuthStateCleanup:
    """Tests for OAuth state management."""

    def test_cleanup_removes_expired_states(self) -> None:
        _oauth_states.clear()
        _oauth_states["fresh"] = datetime.now(UTC)
        _oauth_states["expired"] = datetime.now(UTC) - timedelta(minutes=15)
        _cleanup_expired_states()
        assert "fresh" in _oauth_states
        assert "expired" not in _oauth_states
        _oauth_states.clear()


# ---------------------------------------------------------------------------
# Fixtures for auth endpoint testing
# ---------------------------------------------------------------------------


@pytest.fixture
async def auth_test_db() -> AsyncIterator[AsyncSession]:
    """Create test tables, yield a session, then drop everything."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with test_engine.begin() as conn:
        from sqlalchemy import text

        await conn.execute(text("DELETE FROM users"))

    from tests.conftest import test_session_factory

    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def auth_client() -> AsyncIterator[AsyncClient]:
    """Async test client with auth_router and real test DB."""
    app = FastAPI(title="Auth Test")
    app.include_router(auth_router)
    app.dependency_overrides[get_session] = get_test_session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _make_user(session: AsyncSession, *, github_login: str = "testuser") -> User:
    """Insert a User row and return it."""
    user = User(
        github_id=12345,
        github_login=github_login,
        github_avatar_url=None,
        encrypted_token=None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# get_current_user dependency tests
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    """Tests for the get_current_user FastAPI dependency."""

    async def test_returns_user_for_valid_token(self, auth_test_db: AsyncSession) -> None:
        """Valid JWT cookie resolves to the corresponding User."""
        user = await _make_user(auth_test_db)
        token = _create_jwt(user.id)
        result = await get_current_user(
            session=auth_test_db,
            session_token=token,
        )
        assert result.id == user.id

    async def test_raises_401_when_no_token(self, auth_test_db: AsyncSession) -> None:
        """Missing cookie raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(session=auth_test_db, session_token=None)
        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    async def test_raises_401_for_invalid_token(self, auth_test_db: AsyncSession) -> None:
        """Garbage token raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(session=auth_test_db, session_token="not-a-jwt")
        assert exc_info.value.status_code == 401

    async def test_raises_401_for_expired_token(self, auth_test_db: AsyncSession) -> None:
        """Expired JWT raises 401."""
        from fastapi import HTTPException

        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(minutes=5),
            "iat": datetime.now(UTC) - timedelta(minutes=10),
        }
        expired_token = jwt.encode(payload, "change-me-in-production", algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(session=auth_test_db, session_token=expired_token)
        assert exc_info.value.status_code == 401

    async def test_raises_401_when_user_not_in_db(self, auth_test_db: AsyncSession) -> None:
        """JWT for non-existent user raises 401."""
        from fastapi import HTTPException

        token = _create_jwt(99999)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(session=auth_test_db, session_token=token)
        assert exc_info.value.status_code == 401
        assert "User not found" in exc_info.value.detail

    async def test_syncs_is_admin_flag(self, auth_test_db: AsyncSession) -> None:
        """is_admin is updated when user login is in admin_github_logins."""
        user = await _make_user(auth_test_db, github_login="webwiebe")
        assert not user.is_admin  # starts False

        token = _create_jwt(user.id)
        result = await get_current_user(session=auth_test_db, session_token=token)
        assert result.is_admin is True


# ---------------------------------------------------------------------------
# get_admin_user dependency tests
# ---------------------------------------------------------------------------


class TestGetAdminUser:
    """Tests for the get_admin_user dependency."""

    async def test_returns_user_when_admin(self) -> None:
        """Admin user passes through without error."""
        admin = MagicMock(spec=User)
        admin.is_admin = True
        admin.github_login = "webwiebe"

        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.admin_github_logins = ["webwiebe"]
            result = await get_admin_user(admin)

        assert result is admin

    async def test_raises_403_for_non_admin(self) -> None:
        """Non-admin user raises 403."""
        from fastapi import HTTPException

        user = MagicMock(spec=User)
        user.is_admin = False
        user.github_login = "regularuser"

        with (
            patch("github_tamagotchi.api.auth.settings") as mock_settings,
            pytest.raises(HTTPException) as exc_info,
        ):
            mock_settings.admin_github_logins = ["webwiebe"]
            await get_admin_user(user)

        assert exc_info.value.status_code == 403

    async def test_admin_via_config_even_if_flag_false(self) -> None:
        """User in admin_github_logins is admin even if is_admin flag is False."""
        user = MagicMock(spec=User)
        user.is_admin = False
        user.github_login = "configadmin"

        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.admin_github_logins = ["configadmin"]
            result = await get_admin_user(user)

        assert result is user


# ---------------------------------------------------------------------------
# get_optional_user dependency tests
# ---------------------------------------------------------------------------


class TestGetOptionalUser:
    """Tests for the get_optional_user dependency."""

    async def test_returns_none_when_no_token(self, auth_test_db: AsyncSession) -> None:
        """No token returns None instead of raising."""
        result = await get_optional_user(session=auth_test_db, session_token=None)
        assert result is None

    async def test_returns_none_for_invalid_token(self, auth_test_db: AsyncSession) -> None:
        """Invalid token returns None instead of raising."""
        result = await get_optional_user(session=auth_test_db, session_token="garbage")
        assert result is None

    async def test_returns_none_for_expired_token(self, auth_test_db: AsyncSession) -> None:
        """Expired token returns None."""
        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(minutes=5),
            "iat": datetime.now(UTC) - timedelta(minutes=10),
        }
        expired_token = jwt.encode(payload, "change-me-in-production", algorithm="HS256")
        result = await get_optional_user(session=auth_test_db, session_token=expired_token)
        assert result is None

    async def test_returns_user_for_valid_token(self, auth_test_db: AsyncSession) -> None:
        """Valid token with existing user returns the user."""
        user = await _make_user(auth_test_db)
        token = _create_jwt(user.id)
        result = await get_optional_user(session=auth_test_db, session_token=token)
        assert result is not None
        assert result.id == user.id

    async def test_returns_none_when_user_not_in_db(self, auth_test_db: AsyncSession) -> None:
        """Valid token for non-existent user returns None."""
        token = _create_jwt(99998)
        result = await get_optional_user(session=auth_test_db, session_token=token)
        assert result is None

    async def test_syncs_is_admin_flag(self, auth_test_db: AsyncSession) -> None:
        """is_admin is synced when user login is in admin_github_logins."""
        user = await _make_user(auth_test_db, github_login="webwiebe")
        token = _create_jwt(user.id)
        result = await get_optional_user(session=auth_test_db, session_token=token)
        assert result is not None
        assert result.is_admin is True


# ---------------------------------------------------------------------------
# OAuth login endpoint tests
# ---------------------------------------------------------------------------


class TestLoginGithubEndpoint:
    """Tests for GET /auth/github (OAuth redirect)."""

    async def test_redirects_when_configured(self, auth_client: AsyncClient) -> None:
        """Returns 307 redirect to GitHub when OAuth is configured."""
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = "my-client-id"
            mock_settings.oauth_redirect_uri = "http://localhost/auth/callback"
            response = await auth_client.get("/auth/github", follow_redirects=False)

        assert response.status_code == 307
        assert "github.com/login/oauth/authorize" in response.headers["location"]

    async def test_503_when_oauth_not_configured(self, auth_client: AsyncClient) -> None:
        """Returns 503 when GitHub OAuth client ID is not configured."""
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = None
            response = await auth_client.get("/auth/github")

        assert response.status_code == 503

    async def test_state_stored_in_oauth_states(self, auth_client: AsyncClient) -> None:
        """OAuth state parameter is stored for CSRF validation."""
        _oauth_states.clear()
        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = "my-client-id"
            mock_settings.oauth_redirect_uri = "http://localhost/auth/callback"
            response = await auth_client.get("/auth/github", follow_redirects=False)

        assert response.status_code == 307
        assert len(_oauth_states) == 1
        _oauth_states.clear()


# ---------------------------------------------------------------------------
# OAuth callback early-exit error path tests (no real GitHub calls)
# ---------------------------------------------------------------------------


class TestOAuthCallbackErrors:
    """Tests for early error paths in GET /auth/callback."""

    async def test_400_when_no_code(self, auth_client: AsyncClient) -> None:
        """Missing code parameter returns 400."""
        response = await auth_client.get("/auth/callback?state=something")
        assert response.status_code == 400
        assert "Missing authorization code" in response.json()["detail"]

    async def test_400_when_no_state(self, auth_client: AsyncClient) -> None:
        """Missing state parameter returns 400."""
        response = await auth_client.get("/auth/callback?code=mycode")
        assert response.status_code == 400
        assert "Invalid or expired OAuth state" in response.json()["detail"]

    async def test_400_when_state_not_in_store(self, auth_client: AsyncClient) -> None:
        """Unknown state value returns 400."""
        _oauth_states.clear()
        response = await auth_client.get("/auth/callback?code=mycode&state=unknownstate")
        assert response.status_code == 400

    async def test_503_when_oauth_not_configured(self, auth_client: AsyncClient) -> None:
        """Returns 503 when client_id/secret is missing after state validation."""
        _oauth_states.clear()
        _oauth_states["validstate"] = datetime.now(UTC)

        with patch("github_tamagotchi.api.auth.settings") as mock_settings:
            mock_settings.github_oauth_client_id = None
            mock_settings.github_oauth_client_secret = None
            response = await auth_client.get(
                "/auth/callback?code=mycode&state=validstate"
            )

        assert response.status_code == 503
        _oauth_states.clear()


# ---------------------------------------------------------------------------
# Auth API endpoints — /me and /logout
# ---------------------------------------------------------------------------


class TestMeEndpoint:
    """Tests for GET /auth/me."""

    async def test_returns_user_info(self, auth_client: AsyncClient) -> None:
        """Returns user data for authenticated request."""
        # Create a user in the DB
        from tests.conftest import test_session_factory

        async with test_session_factory() as session:
            user = await _make_user(session, github_login="apitestuser")

        token = _create_jwt(user.id)
        response = await auth_client.get(
            "/auth/me", cookies={"session_token": token}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["github_login"] == "apitestuser"

    async def test_401_without_token(self, auth_client: AsyncClient) -> None:
        """Returns 401 when no session cookie is present."""
        response = await auth_client.get("/auth/me")
        assert response.status_code == 401


class TestLogoutEndpoint:
    """Tests for POST /auth/logout."""

    async def test_logout_returns_200(self, auth_client: AsyncClient) -> None:
        """Logout returns 200 and clears session cookie."""
        response = await auth_client.post("/auth/logout")
        assert response.status_code == 200
