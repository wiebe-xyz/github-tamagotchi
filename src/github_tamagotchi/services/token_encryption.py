"""Token encryption/decryption using Fernet symmetric encryption."""

from cryptography.fernet import Fernet

from github_tamagotchi.core.config import settings


def _get_fernet() -> Fernet:
    """Get a Fernet instance using the configured encryption key."""
    key = settings.token_encryption_key
    if not key:
        raise ValueError("token_encryption_key is not configured")
    return Fernet(key.encode())


def encrypt_token(token: str) -> str:
    """Encrypt a GitHub access token for storage."""
    f = _get_fernet()
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a stored GitHub access token."""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()
