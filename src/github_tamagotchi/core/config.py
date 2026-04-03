"""Application configuration."""

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
    image_generation_provider: str = "openrouter"  # "openrouter" or "comfyui"

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

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

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


settings = Settings()
