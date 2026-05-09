"""Application configuration."""

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    app_name: str = "GitHub Tamagotchi"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://localhost/tamagotchi"

    # GitHub
    github_token: str | None = None
    github_poll_interval_minutes: int = 30
    github_webhook_secret: str | None = None

    # GitHub OAuth
    github_oauth_client_id: str | None = None
    github_oauth_client_secret: str | None = None
    oauth_redirect_uri: str = "http://localhost:8000/auth/callback"

    # JWT / Session
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    # Token encryption key (Fernet, base64-encoded 32 bytes)
    token_encryption_key: str | None = None

    # ComfyUI
    comfyui_url: str | None = None
    comfyui_cf_access_client_id: str | None = None
    comfyui_cf_access_client_secret: str | None = None
    comfyui_timeout: float = 120.0

    # Image generation
    image_generation_enabled: bool = True
    image_generation_provider: Literal["openrouter", "comfyui"] = "openrouter"

    # OpenRouter
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-2.5-flash-image"
    openrouter_timeout: float = 60.0

    # MinIO/S3 storage
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "tamagotchi"
    minio_secure: bool = False

    # Public base URL (used for absolute URLs in meta tags, embeds, etc.)
    base_url: str = "https://tamagotchi.nijmegen.wiebe.xyz"

    # Server
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # Admin
    admin_github_logins: list[str] = ["webwiebe"]

    # OpenTelemetry
    otel_enabled: bool = False
    otel_service_name: str = "github-tamagotchi"
    otel_traces_sample_rate: float = 1.0

    # Sentry
    sentry_dsn: str | None = None

    # FunnelBarn analytics (client-side, public key)
    funnelbarn_api_key: str | None = None

    # BugBarn
    bugbarn_endpoint: str | None = None
    bugbarn_api_key: str | None = None
    bugbarn_project: str = "github-tamagotchi"

    # Alerting
    alerting_enabled: bool = True
    alert_slack_webhook: str | None = None
    alert_discord_webhook: str | None = None
    alert_poll_failure_threshold: int = 2
    alert_error_rate_threshold: float = 0.05
    alert_github_rate_limit_threshold: int = 100
    alert_db_slow_query_ms: int = 500
    alert_dying_pets_pct: float = 0.10
    alert_death_spike_count: int = 5
    alert_check_interval_minutes: int = 5

    # Web Push / VAPID
    # Generate keys with: python -m github_tamagotchi.scripts.gen_vapid_keys
    vapid_private_key: str | None = None  # base64url-encoded DER EC private key
    vapid_public_key: str | None = None   # base64url-encoded uncompressed EC public key
    vapid_contact_email: str = "admin@example.com"

    @field_validator("token_encryption_key", mode="before")
    @classmethod
    def validate_token_encryption_key(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        import base64

        try:
            decoded = base64.urlsafe_b64decode(v)
        except Exception as exc:
            raise ValueError(
                "token_encryption_key is not valid base64. "
                "Generate one with: python -c "
                "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            ) from exc
        if len(decoded) != 32:
            raise ValueError(
                f"token_encryption_key must decode to 32 bytes, got {len(decoded)}. "
                "Generate one with: python -c "
                "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        return v

    @field_validator(
        "oauth_redirect_uri",
        "comfyui_url",
        "base_url",
        "alert_slack_webhook",
        "alert_discord_webhook",
        "bugbarn_endpoint",
        mode="before",
    )
    @classmethod
    def validate_url_format(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from urllib.parse import urlparse

        parsed = urlparse(v)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL format: {v!r}")
        return v


settings = Settings()
