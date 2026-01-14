"""Application configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    app_name: str = "GitHub Tamagotchi"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://localhost/tamagotchi"

    # GitHub
    github_token: str | None = None
    github_poll_interval_minutes: int = 30

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # ComfyUI image generation
    comfyui_url: str | None = None
    comfyui_timeout_seconds: int = 300
    image_generation_enabled: bool = True

    # MinIO/S3 storage
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "tamagotchi"
    minio_secure: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
