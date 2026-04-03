"""Unit tests for authentication module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest

from github_tamagotchi.api.auth import (
    _cleanup_expired_states,
    _create_jwt,
    _decode_jwt,
    _oauth_states,
)


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
