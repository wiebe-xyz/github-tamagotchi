"""MinIO/S3 storage service for pet images."""

import io
from typing import TYPE_CHECKING

import structlog
from minio import Minio
from minio.error import S3Error

from github_tamagotchi.core.config import settings

if TYPE_CHECKING:
    from minio.datatypes import Object as MinioObject

logger = structlog.get_logger()


class StorageService:
    """Service for storing and retrieving pet images from MinIO/S3."""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        secure: bool | None = None,
    ) -> None:
        """Initialize MinIO client with configuration."""
        self.endpoint = endpoint or settings.minio_endpoint
        self.access_key = access_key or settings.minio_access_key
        self.secret_key = secret_key or settings.minio_secret_key
        self.bucket = bucket or settings.minio_bucket
        self.secure = secure if secure is not None else settings.minio_secure

        self._client: Minio | None = None

    @property
    def client(self) -> Minio:
        """Get or create MinIO client."""
        if self._client is None:
            if not self.endpoint or not self.access_key or not self.secret_key:
                raise ValueError("MinIO configuration incomplete")
            self._client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    def _get_object_path(self, owner: str, repo: str, stage: str) -> str:
        """Build the object path for a pet image."""
        return f"pets/{owner}/{repo}/{stage}.png"

    async def ensure_bucket_exists(self) -> None:
        """Ensure the bucket exists, creating it if necessary."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("Created bucket", bucket=self.bucket)
        except S3Error as e:
            logger.error("Failed to ensure bucket exists", error=str(e))
            raise

    async def upload_image(
        self, owner: str, repo: str, stage: str, image_data: bytes
    ) -> str:
        """Upload a pet image to storage.

        Args:
            owner: Repository owner
            repo: Repository name
            stage: Pet stage (egg, baby, child, teen, adult, elder)
            image_data: PNG image bytes

        Returns:
            The object path where the image was stored
        """
        object_path = self._get_object_path(owner, repo, stage)

        try:
            await self.ensure_bucket_exists()
            self.client.put_object(
                self.bucket,
                object_path,
                io.BytesIO(image_data),
                length=len(image_data),
                content_type="image/png",
            )
            logger.info(
                "Uploaded pet image",
                owner=owner,
                repo=repo,
                stage=stage,
                path=object_path,
            )
            return object_path
        except S3Error as e:
            logger.error("Failed to upload image", error=str(e), path=object_path)
            raise

    async def get_image(self, owner: str, repo: str, stage: str) -> bytes | None:
        """Retrieve a pet image from storage.

        Args:
            owner: Repository owner
            repo: Repository name
            stage: Pet stage

        Returns:
            Image bytes or None if not found
        """
        object_path = self._get_object_path(owner, repo, stage)

        try:
            response = self.client.get_object(self.bucket, object_path)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.debug("Image not found", path=object_path)
                return None
            logger.error("Failed to get image", error=str(e), path=object_path)
            raise

    async def image_exists(self, owner: str, repo: str, stage: str) -> bool:
        """Check if a pet image exists in storage."""
        object_path = self._get_object_path(owner, repo, stage)

        try:
            self.client.stat_object(self.bucket, object_path)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            raise

    async def delete_images(self, owner: str, repo: str) -> None:
        """Delete all images for a pet."""
        stages = ["egg", "baby", "child", "teen", "adult", "elder"]
        for stage in stages:
            object_path = self._get_object_path(owner, repo, stage)
            try:
                self.client.remove_object(self.bucket, object_path)
                logger.debug("Deleted image", path=object_path)
            except S3Error as e:
                if e.code != "NoSuchKey":
                    logger.warning("Failed to delete image", error=str(e), path=object_path)

    async def list_pet_images(self, owner: str, repo: str) -> list[str]:
        """List all images for a pet.

        Returns:
            List of stage names that have images
        """
        prefix = f"pets/{owner}/{repo}/"
        stages: list[str] = []

        try:
            objects: list[MinioObject] = list(
                self.client.list_objects(self.bucket, prefix=prefix)
            )
            for obj in objects:
                if obj.object_name and obj.object_name.endswith(".png"):
                    stage = obj.object_name.replace(prefix, "").replace(".png", "")
                    stages.append(stage)
        except S3Error as e:
            logger.error("Failed to list images", error=str(e), prefix=prefix)
            raise

        return stages

    def get_public_url(self, owner: str, repo: str, stage: str) -> str:
        """Get the public URL for a pet image.

        Note: This assumes the bucket has public read access configured,
        or returns a presigned URL for private buckets.
        """
        object_path = self._get_object_path(owner, repo, stage)
        protocol = "https" if self.secure else "http"
        return f"{protocol}://{self.endpoint}/{self.bucket}/{object_path}"
