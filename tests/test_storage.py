"""Tests for MinIO/S3 storage service."""

import io
from unittest.mock import MagicMock, patch

import pytest
from minio.error import S3Error
from PIL import Image

from github_tamagotchi.services.storage import StorageService


def _make_png(width: int = 2, height: int = 2) -> bytes:
    """Create a minimal valid PNG image for testing."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def mock_minio_client() -> MagicMock:
    """Create a mock MinIO client."""
    return MagicMock()


@pytest.fixture
def storage_service(mock_minio_client: MagicMock) -> StorageService:
    """Create a storage service with mock client."""
    service = StorageService(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        bucket="test-bucket",
        secure=False,
    )
    service._client = mock_minio_client
    return service


class TestStorageService:
    """Tests for StorageService."""

    def test_get_object_path(self, storage_service: StorageService) -> None:
        """Test object path generation."""
        path = storage_service._get_object_path("owner", "repo", "egg")
        assert path == "pets/owner/repo/egg.png"

    def test_get_object_path_with_special_characters(
        self, storage_service: StorageService
    ) -> None:
        """Test object path with special repo names."""
        path = storage_service._get_object_path("owner-name", "repo-name", "baby")
        assert path == "pets/owner-name/repo-name/baby.png"

    def test_get_object_path_rejects_path_traversal(
        self, storage_service: StorageService
    ) -> None:
        """Test that path traversal characters are rejected."""
        with pytest.raises(ValueError, match="Invalid owner"):
            storage_service._get_object_path("../etc", "repo", "egg")

    def test_get_object_path_rejects_slashes(
        self, storage_service: StorageService
    ) -> None:
        """Test that slashes in input are rejected."""
        with pytest.raises(ValueError, match="Invalid repo"):
            storage_service._get_object_path("owner", "repo/../../etc", "egg")

    def test_get_object_path_rejects_empty(
        self, storage_service: StorageService
    ) -> None:
        """Test that empty owner/repo is rejected."""
        with pytest.raises(ValueError, match="Invalid owner"):
            storage_service._get_object_path("", "repo", "egg")

    async def test_ensure_bucket_exists_creates_bucket(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test bucket creation when it doesn't exist."""
        mock_minio_client.bucket_exists.return_value = False

        await storage_service.ensure_bucket_exists()

        mock_minio_client.bucket_exists.assert_called_once_with("test-bucket")
        mock_minio_client.make_bucket.assert_called_once_with("test-bucket")

    async def test_ensure_bucket_exists_skips_existing(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test that existing bucket is not recreated."""
        mock_minio_client.bucket_exists.return_value = True

        await storage_service.ensure_bucket_exists()

        mock_minio_client.bucket_exists.assert_called_once()
        mock_minio_client.make_bucket.assert_not_called()

    async def test_upload_image(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test image upload with background removal."""
        mock_minio_client.bucket_exists.return_value = True
        image_data = _make_png()

        path = await storage_service.upload_image("owner", "repo", "egg", image_data)

        assert path == "pets/owner/repo/egg.png"
        mock_minio_client.put_object.assert_called_once()
        call_args = mock_minio_client.put_object.call_args
        assert call_args[0][0] == "test-bucket"
        assert call_args[0][1] == "pets/owner/repo/egg.png"

    async def test_get_image_found(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test retrieving existing image — prefers idle frame over sprite sheet."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"image data"
        mock_minio_client.get_object.return_value = mock_response

        result = await storage_service.get_image("owner", "repo", "baby")

        assert result == b"image data"
        mock_minio_client.get_object.assert_called_once_with(
            "test-bucket", "pets/owner/repo/baby_frame_0.png"
        )
        mock_response.close.assert_called_once()
        mock_response.release_conn.assert_called_once()

    async def test_get_image_not_found(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test retrieving non-existent image."""
        error = S3Error(
            code="NoSuchKey",
            message="Not found",
            resource="test",
            request_id="123",
            host_id="host",
            response="response",
        )
        mock_minio_client.get_object.side_effect = error

        result = await storage_service.get_image("owner", "repo", "child")

        assert result is None

    async def test_image_exists_true(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test checking if image exists."""
        mock_minio_client.stat_object.return_value = MagicMock()

        result = await storage_service.image_exists("owner", "repo", "teen")

        assert result is True
        mock_minio_client.stat_object.assert_called_once_with(
            "test-bucket", "pets/owner/repo/teen.png"
        )

    async def test_image_exists_false(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test checking if image doesn't exist."""
        error = S3Error(
            code="NoSuchKey",
            message="Not found",
            resource="test",
            request_id="123",
            host_id="host",
            response="response",
        )
        mock_minio_client.stat_object.side_effect = error

        result = await storage_service.image_exists("owner", "repo", "adult")

        assert result is False

    async def test_delete_images(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test deleting all pet images."""
        await storage_service.delete_images("owner", "repo")

        assert mock_minio_client.remove_object.call_count == 6
        expected_stages = ["egg", "baby", "child", "teen", "adult", "elder"]
        for stage in expected_stages:
            mock_minio_client.remove_object.assert_any_call(
                "test-bucket", f"pets/owner/repo/{stage}.png"
            )

    async def test_list_pet_images(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Test listing all images for a pet."""
        mock_objects = [
            MagicMock(object_name="pets/owner/repo/egg.png"),
            MagicMock(object_name="pets/owner/repo/baby.png"),
        ]
        mock_minio_client.list_objects.return_value = mock_objects

        result = await storage_service.list_pet_images("owner", "repo")

        assert result == ["egg", "baby"]
        mock_minio_client.list_objects.assert_called_once_with(
            "test-bucket", prefix="pets/owner/repo/"
        )

    def test_get_public_url(self, storage_service: StorageService) -> None:
        """Test public URL generation."""
        url = storage_service.get_public_url("owner", "repo", "elder")

        assert url == "http://localhost:9000/test-bucket/pets/owner/repo/elder.png"

    def test_get_public_url_secure(self) -> None:
        """Test public URL generation with HTTPS."""
        service = StorageService(
            endpoint="minio.example.com",
            access_key="key",
            secret_key="secret",
            bucket="bucket",
            secure=True,
        )
        url = service.get_public_url("owner", "repo", "egg")

        assert url == "https://minio.example.com/bucket/pets/owner/repo/egg.png"


class TestStorageServiceConfiguration:
    """Tests for StorageService configuration."""

    def test_missing_endpoint_raises_error(self) -> None:
        """Test that missing endpoint raises error on client access."""
        service = StorageService(
            endpoint=None,
            access_key="key",
            secret_key="secret",
        )

        with pytest.raises(ValueError, match="MinIO configuration incomplete"):
            _ = service.client

    def test_missing_access_key_raises_error(self) -> None:
        """Test that missing access key raises error."""
        service = StorageService(
            endpoint="localhost:9000",
            access_key=None,
            secret_key="secret",
        )

        with pytest.raises(ValueError, match="MinIO configuration incomplete"):
            _ = service.client

    def test_missing_secret_key_raises_error(self) -> None:
        """Test that missing secret key raises error."""
        service = StorageService(
            endpoint="localhost:9000",
            access_key="key",
            secret_key=None,
        )

        with pytest.raises(ValueError, match="MinIO configuration incomplete"):
            _ = service.client

    @patch("github_tamagotchi.services.storage.Minio")
    def test_client_creation(self, mock_minio_class: MagicMock) -> None:
        """Test MinIO client is created correctly."""
        service = StorageService(
            endpoint="localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin123",
            secure=False,
        )

        _ = service.client

        mock_minio_class.assert_called_once_with(
            "localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin123",
            secure=False,
        )


class TestAnimatedGifStorage:
    """Tests for animated GIF and sprite sheet storage methods."""

    @pytest.fixture
    def mock_minio_client(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def storage_service(self, mock_minio_client: MagicMock) -> StorageService:
        service = StorageService(
            endpoint="localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="test-bucket",
            secure=False,
        )
        service._client = mock_minio_client
        return service

    def test_get_spritesheet_path(self, storage_service: StorageService) -> None:
        """Sprite sheet path is under the pet's prefix."""
        path = storage_service._get_spritesheet_path("owner", "repo", "adult")
        assert path == "pets/owner/repo/adult_spritesheet.png"

    def test_get_frame_path(self, storage_service: StorageService) -> None:
        """Frame path includes the frame index."""
        path = storage_service._get_frame_path("owner", "repo", "adult", 3)
        assert path == "pets/owner/repo/adult_frame_3.png"

    def test_get_animated_gif_path(self, storage_service: StorageService) -> None:
        """Animated GIF path ends with _animated.gif."""
        path = storage_service._get_animated_gif_path("owner", "repo", "baby")
        assert path == "pets/owner/repo/baby_animated.gif"

    async def test_upload_sprite_sheet(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """Upload sprite sheet stores PNG at expected path."""
        mock_minio_client.bucket_exists.return_value = True
        data = _make_png()

        path = await storage_service.upload_sprite_sheet("owner", "repo", "adult", data)

        assert path == "pets/owner/repo/adult_spritesheet.png"
        mock_minio_client.put_object.assert_called_once()

    async def test_get_sprite_sheet_found(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """get_sprite_sheet returns bytes when object exists."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"sheet_data"
        mock_minio_client.get_object.return_value = mock_response

        result = await storage_service.get_sprite_sheet("owner", "repo", "adult")

        assert result == b"sheet_data"

    async def test_get_sprite_sheet_not_found(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """get_sprite_sheet returns None when object does not exist."""
        error = S3Error(
            code="NoSuchKey",
            message="Not found",
            resource="test",
            request_id="123",
            host_id="host",
            response="response",
        )
        mock_minio_client.get_object.side_effect = error

        result = await storage_service.get_sprite_sheet("owner", "repo", "adult")

        assert result is None

    async def test_upload_frame(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """upload_frame stores PNG at frame-specific path."""
        mock_minio_client.bucket_exists.return_value = True
        data = _make_png()

        path = await storage_service.upload_frame("owner", "repo", "adult", 2, data)

        assert path == "pets/owner/repo/adult_frame_2.png"
        mock_minio_client.put_object.assert_called_once()

    async def test_get_frame_found(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """get_frame returns bytes when frame exists."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"frame_data"
        mock_minio_client.get_object.return_value = mock_response

        result = await storage_service.get_frame("owner", "repo", "adult", 1)

        assert result == b"frame_data"

    async def test_upload_animated_gif(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """upload_animated_gif stores GIF at expected path."""
        mock_minio_client.bucket_exists.return_value = True
        gif_data = b"GIF89a..."

        path = await storage_service.upload_animated_gif("owner", "repo", "adult", gif_data)

        assert path == "pets/owner/repo/adult_animated.gif"
        mock_minio_client.put_object.assert_called_once()

    async def test_get_animated_gif_found(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """get_animated_gif returns bytes when GIF exists."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"gif_data"
        mock_minio_client.get_object.return_value = mock_response

        result = await storage_service.get_animated_gif("owner", "repo", "adult")

        assert result == b"gif_data"

    async def test_get_animated_gif_not_found(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """get_animated_gif returns None when GIF does not exist."""
        error = S3Error(
            code="NoSuchKey",
            message="Not found",
            resource="test",
            request_id="123",
            host_id="host",
            response="response",
        )
        mock_minio_client.get_object.side_effect = error

        result = await storage_service.get_animated_gif("owner", "repo", "adult")

        assert result is None

    async def test_animated_gif_exists_true(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """animated_gif_exists returns True when GIF exists."""
        mock_minio_client.stat_object.return_value = MagicMock()

        result = await storage_service.animated_gif_exists("owner", "repo", "adult")

        assert result is True

    async def test_animated_gif_exists_false(
        self, storage_service: StorageService, mock_minio_client: MagicMock
    ) -> None:
        """animated_gif_exists returns False when GIF does not exist."""
        error = S3Error(
            code="NoSuchKey",
            message="Not found",
            resource="test",
            request_id="123",
            host_id="host",
            response="response",
        )
        mock_minio_client.stat_object.side_effect = error

        result = await storage_service.animated_gif_exists("owner", "repo", "adult")

        assert result is False
