"""Integration tests for pet media endpoint routing.

Verifies that all /image/ sub-routes are registered and reachable —
i.e., they return domain-specific status codes (400, 404, 503), never
a generic FastAPI 404 {"detail": "Not Found"} that indicates a missing route.
"""

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image


def _png_bytes() -> bytes:
    img = Image.new("RGBA", (8, 8), color=(100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mock_storage(
    *,
    image: bytes | None = None,
    frame: bytes | None = None,
    sheet: bytes | None = None,
    gif: bytes | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.get_image = AsyncMock(return_value=image)
    mock.get_frame = AsyncMock(return_value=frame)
    mock.get_sprite_sheet = AsyncMock(return_value=sheet)
    mock.get_animated_gif = AsyncMock(return_value=gif)
    mock.upload_image = AsyncMock(return_value="path")
    mock.upload_sprite_sheet = AsyncMock(return_value="path")
    mock.upload_frame = AsyncMock(return_value="path")
    mock.upload_animated_gif = AsyncMock(return_value="path")
    mock.ensure_bucket_exists = AsyncMock()
    return mock


def _settings_with_minio() -> MagicMock:
    s = MagicMock()
    s.minio_endpoint = "localhost:9000"
    s.minio_access_key = "test"
    s.minio_secret_key = "test"
    s.minio_bucket = "test"
    s.minio_secure = False
    s.image_generation_enabled = False
    s.image_generation_provider = "openrouter"
    return s


def _patches(mock_storage: MagicMock, mock_settings: MagicMock | None = None):
    """Context manager that patches settings + StorageService."""
    import contextlib

    return contextlib.ExitStack()


OWNER, REPO, STAGE = "testowner", "testrepo", "adult"


class TestMediaRouteRegistration:
    """Every /image/ sub-route must be reachable (not a generic 404).

    A generic 404 has {"detail": "Not Found"} — our custom 404s always
    have a more specific detail string.  These tests assert the route
    *exists* by checking for a non-generic response.
    """

    @staticmethod
    def _is_generic_404(response) -> bool:
        """True if FastAPI returned its default 'route not found' 404."""
        return response.status_code == 404 and response.json().get("detail") == "Not Found"

    # -- /image/{stage} --

    async def test_image_stage_route_exists(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}"
            )
        assert not self._is_generic_404(resp), "Route /image/{stage} not registered"

    async def test_image_invalid_stage_returns_400(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/bogus_stage"
            )
        assert resp.status_code == 400

    # -- /image/{stage}/sheet --

    async def test_sheet_route_exists(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/sheet"
            )
        assert not self._is_generic_404(resp), "Route /image/{stage}/sheet not registered"

    async def test_sheet_returns_data_when_exists(self, async_client: AsyncClient) -> None:
        png = _png_bytes()
        storage = _mock_storage(sheet=png)
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/sheet"
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    async def test_sheet_missing_returns_custom_404(self, async_client: AsyncClient) -> None:
        storage = _mock_storage(sheet=None)
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/sheet"
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Sprite sheet not found"

    async def test_sheet_invalid_stage_returns_400(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/bogus/sheet"
            )
        assert resp.status_code == 400

    # -- /image/{stage}/frame/{idx} --

    async def test_frame_route_exists(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/frame/0"
            )
        assert not self._is_generic_404(resp), "Route /image/{stage}/frame/{idx} not registered"

    async def test_frame_returns_data_when_exists(self, async_client: AsyncClient) -> None:
        png = _png_bytes()
        storage = _mock_storage(frame=png)
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/frame/0"
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    async def test_frame_missing_returns_custom_404(self, async_client: AsyncClient) -> None:
        storage = _mock_storage(frame=None)
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/frame/0"
            )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Frame not found"

    async def test_frame_invalid_stage_returns_400(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/bogus/frame/0"
            )
        assert resp.status_code == 400

    async def test_frame_index_out_of_range_returns_400(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/frame/6"
            )
        assert resp.status_code == 400

    # -- /image/{stage}/animated --

    async def test_animated_route_exists(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/animated"
            )
        assert not self._is_generic_404(resp), "Route /image/{stage}/animated not registered"

    async def test_animated_invalid_stage_returns_400(self, async_client: AsyncClient) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/bogus/animated"
            )
        assert resp.status_code == 400


class TestMediaRouteNoOverlap:
    """Verify that /image/{stage} doesn't accidentally match sub-routes.

    e.g., GET /image/adult/sheet should NOT hit the /image/{stage} handler
    with stage="adult" and an extra path segment.
    """

    async def test_sheet_url_not_caught_by_stage_handler(
        self, async_client: AsyncClient
    ) -> None:
        """The /image/{stage} handler should never see stage='adult' for a /sheet URL."""
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/sheet"
            )
        # If the stage handler caught this, it'd return 400 ("Invalid stage")
        # because "adult" is valid but "sheet" would be in the URL weirdly,
        # OR it'd return the image. Either way, we should get our custom 404.
        assert resp.status_code in (200, 404)
        if resp.status_code == 404:
            assert "Sprite sheet" in resp.json()["detail"]

    async def test_frame_url_not_caught_by_stage_handler(
        self, async_client: AsyncClient
    ) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(
                f"/api/v1/pets/{OWNER}/{REPO}/image/{STAGE}/frame/0"
            )
        assert resp.status_code in (200, 404)
        if resp.status_code == 404:
            assert "Frame" in resp.json()["detail"]


class TestMediaRoutesInvalidRepo:
    """An owner or repo that cannot name a stored object is a missing image.

    Storage raises ValueError for such a name. The routes used to log that at
    error and answer 503, so a crawler asking for /pets/webwiebe/$/image/egg
    opened a BugBarn issue (GT-10). They now answer 404 without asking storage.
    """

    ROUTES = [
        "/api/v1/pets/{owner}/{repo}/image/egg",
        "/api/v1/pets/{owner}/{repo}/image/egg/animated",
        "/api/v1/pets/{owner}/{repo}/image/egg/sheet",
        "/api/v1/pets/{owner}/{repo}/image/egg/frame/0",
    ]

    @pytest.mark.parametrize("route", ROUTES)
    @pytest.mark.parametrize(
        ("owner", "repo"), [("webwiebe", "$"), ("we$bwiebe", REPO), (OWNER, "café")]
    )
    async def test_returns_404_without_touching_storage(
        self, async_client: AsyncClient, route: str, owner: str, repo: str
    ) -> None:
        storage = _mock_storage()
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
            patch("github_tamagotchi.api.routes.v1.pets.media.logger") as logger,
        ):
            resp = await async_client.get(route.format(owner=owner, repo=repo))

        assert resp.status_code == 404
        assert resp.json() == {"detail": "Image not found"}
        storage.get_image.assert_not_called()
        storage.get_animated_gif.assert_not_called()
        storage.get_sprite_sheet.assert_not_called()
        storage.get_frame.assert_not_called()
        logger.error.assert_not_called()
        logger.warning.assert_called_once()

    async def test_valid_repo_still_reaches_storage(self, async_client: AsyncClient) -> None:
        storage = _mock_storage(image=_png_bytes())
        with (
            patch("github_tamagotchi.api.routes.settings", _settings_with_minio()),
            patch("github_tamagotchi.api.routes.StorageService", return_value=storage),
        ):
            resp = await async_client.get(f"/api/v1/pets/{OWNER}/my-repo.js/image/egg")

        assert resp.status_code == 200
        storage.get_image.assert_awaited_once_with(OWNER, "my-repo.js", "egg")
