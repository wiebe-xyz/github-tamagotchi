"""Tests for configuration settings."""

import os
from unittest.mock import patch

from github_tamagotchi.core.config import Settings


class TestSettingsDefaults:
    """Tests for default configuration values."""

    def test_default_app_name(self) -> None:
        """Default app name should be 'GitHub Tamagotchi'."""
        settings = Settings()
        assert settings.app_name == "GitHub Tamagotchi"

    def test_default_debug_false(self) -> None:
        """Debug mode should be False by default."""
        settings = Settings()
        assert settings.debug is False

    def test_default_database_url(self) -> None:
        """Default database URL should use localhost."""
        settings = Settings()
        assert "localhost" in settings.database_url
        assert "tamagotchi" in settings.database_url

    def test_default_github_token_none(self) -> None:
        """GitHub token should be None by default."""
        settings = Settings()
        assert settings.github_token is None

    def test_default_poll_interval(self) -> None:
        """Default poll interval should be 30 minutes."""
        settings = Settings()
        assert settings.github_poll_interval_minutes == 30

    def test_default_host(self) -> None:
        """Default host should be 0.0.0.0."""
        settings = Settings()
        assert settings.host == "0.0.0.0"

    def test_default_port(self) -> None:
        """Default port should be 8000."""
        settings = Settings()
        assert settings.port == 8000


class TestSettingsFromEnvironment:
    """Tests for loading settings from environment variables."""

    def test_app_name_from_env(self) -> None:
        """App name should be loadable from environment."""
        with patch.dict(os.environ, {"APP_NAME": "Test App"}):
            settings = Settings()
            assert settings.app_name == "Test App"

    def test_debug_from_env(self) -> None:
        """Debug mode should be loadable from environment."""
        with patch.dict(os.environ, {"DEBUG": "true"}):
            settings = Settings()
            assert settings.debug is True

    def test_database_url_from_env(self) -> None:
        """Database URL should be loadable from environment."""
        test_url = "postgresql+asyncpg://user:pass@db/testdb"
        with patch.dict(os.environ, {"DATABASE_URL": test_url}):
            settings = Settings()
            assert settings.database_url == test_url

    def test_github_token_from_env(self) -> None:
        """GitHub token should be loadable from environment."""
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123"}):
            settings = Settings()
            assert settings.github_token == "ghp_test123"

    def test_poll_interval_from_env(self) -> None:
        """Poll interval should be loadable from environment."""
        with patch.dict(os.environ, {"GITHUB_POLL_INTERVAL_MINUTES": "60"}):
            settings = Settings()
            assert settings.github_poll_interval_minutes == 60

    def test_host_from_env(self) -> None:
        """Host should be loadable from environment."""
        with patch.dict(os.environ, {"HOST": "127.0.0.1"}):
            settings = Settings()
            assert settings.host == "127.0.0.1"

    def test_port_from_env(self) -> None:
        """Port should be loadable from environment."""
        with patch.dict(os.environ, {"PORT": "3000"}):
            settings = Settings()
            assert settings.port == 3000


class TestSettingsTypes:
    """Tests for settings type validation."""

    def test_debug_is_bool(self) -> None:
        """Debug setting should be a boolean."""
        settings = Settings()
        assert isinstance(settings.debug, bool)

    def test_port_is_int(self) -> None:
        """Port setting should be an integer."""
        settings = Settings()
        assert isinstance(settings.port, int)

    def test_poll_interval_is_int(self) -> None:
        """Poll interval should be an integer."""
        settings = Settings()
        assert isinstance(settings.github_poll_interval_minutes, int)

    def test_database_url_is_string(self) -> None:
        """Database URL should be a string."""
        settings = Settings()
        assert isinstance(settings.database_url, str)
