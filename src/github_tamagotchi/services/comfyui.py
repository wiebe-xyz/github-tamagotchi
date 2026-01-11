"""ComfyUI API service for image generation."""

from dataclasses import dataclass

import httpx
import structlog

from github_tamagotchi.core.config import settings

logger = structlog.get_logger()


@dataclass
class ComfyUIStatus:
    """Status information from ComfyUI system_stats endpoint."""

    available: bool
    queue_remaining: int | None = None
    cuda_available: bool | None = None


class ComfyUIService:
    """Service for interacting with ComfyUI API."""

    def __init__(
        self,
        url: str | None = None,
        cf_access_client_id: str | None = None,
        cf_access_client_secret: str | None = None,
    ) -> None:
        """Initialize with ComfyUI URL and optional Cloudflare Access credentials."""
        self.url = url or settings.comfyui_url
        self.cf_access_client_id = (
            cf_access_client_id or settings.comfyui_cf_access_client_id
        )
        self.cf_access_client_secret = (
            cf_access_client_secret or settings.comfyui_cf_access_client_secret
        )

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with Cloudflare Access authentication if configured."""
        headers: dict[str, str] = {}
        if self.cf_access_client_id and self.cf_access_client_secret:
            headers["CF-Access-Client-Id"] = self.cf_access_client_id
            headers["CF-Access-Client-Secret"] = self.cf_access_client_secret
        return headers

    async def check_health(self) -> ComfyUIStatus:
        """Check if ComfyUI is available and get system stats."""
        if not self.url:
            logger.debug("ComfyUI URL not configured")
            return ComfyUIStatus(available=False)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/system_stats",
                    headers=self._get_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

                devices = data.get("devices", [])
                cuda_available = any(
                    d.get("type") == "cuda" for d in devices
                ) if devices else None

                return ComfyUIStatus(
                    available=True,
                    queue_remaining=data.get("exec_info", {}).get("queue_remaining"),
                    cuda_available=cuda_available,
                )
        except httpx.TimeoutException:
            logger.warning("ComfyUI health check timed out", url=self.url)
            return ComfyUIStatus(available=False)
        except httpx.HTTPStatusError as e:
            logger.warning(
                "ComfyUI health check failed",
                url=self.url,
                status_code=e.response.status_code,
            )
            return ComfyUIStatus(available=False)
        except Exception as e:
            logger.warning("ComfyUI health check error", url=self.url, error=str(e))
            return ComfyUIStatus(available=False)
