"""Unit tests for token encryption."""

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from github_tamagotchi.services.token_encryption import decrypt_token, encrypt_token


class TestTokenEncryption:
    """Tests for Fernet token encryption/decryption."""

    @pytest.fixture(autouse=True)
    def _setup_key(self) -> None:
        self.key = Fernet.generate_key().decode()

    def test_encrypt_decrypt_roundtrip(self) -> None:
        with patch("github_tamagotchi.services.token_encryption.settings") as mock_settings:
            mock_settings.token_encryption_key = self.key
            original = "ghp_abc123def456"
            encrypted = encrypt_token(original)
            assert encrypted != original
            decrypted = decrypt_token(encrypted)
            assert decrypted == original

    def test_encrypt_without_key_raises(self) -> None:
        with patch("github_tamagotchi.services.token_encryption.settings") as mock_settings:
            mock_settings.token_encryption_key = None
            with pytest.raises(ValueError, match="token_encryption_key"):
                encrypt_token("some-token")

    def test_decrypt_with_wrong_key_raises(self) -> None:
        with patch("github_tamagotchi.services.token_encryption.settings") as mock_settings:
            mock_settings.token_encryption_key = self.key
            encrypted = encrypt_token("test-token")
        wrong_key = Fernet.generate_key().decode()
        with patch("github_tamagotchi.services.token_encryption.settings") as mock_settings:
            mock_settings.token_encryption_key = wrong_key
            with pytest.raises(Exception):  # noqa: B017
                decrypt_token(encrypted)
