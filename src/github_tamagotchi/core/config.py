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

    # ComfyUI
    comfyui_url: str = "http://localhost:8188"
    comfyui_timeout: float = 120.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
