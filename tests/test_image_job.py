"""Tests for ImageGenerationJob model and JobStatus enum."""

from github_tamagotchi.models.image_job import ImageGenerationJob, JobStatus


class TestJobStatusEnum:
    """Tests for JobStatus enum."""

    def test_all_statuses_defined(self) -> None:
        """All expected statuses should be defined."""
        expected_statuses = ["pending", "processing", "completed", "failed"]
        actual_statuses = [status.value for status in JobStatus]
        assert actual_statuses == expected_statuses

    def test_status_count(self) -> None:
        """Should have exactly 4 job statuses."""
        assert len(JobStatus) == 4

    def test_statuses_are_strings(self) -> None:
        """Status values should be lowercase strings."""
        for status in JobStatus:
            assert isinstance(status.value, str)
            assert status.value.islower()

    def test_status_string_representation(self) -> None:
        """JobStatus should have proper string representation."""
        assert JobStatus.PENDING.value == "pending"
        assert str(JobStatus.PENDING) == "JobStatus.PENDING"


class TestImageGenerationJobModel:
    """Tests for ImageGenerationJob SQLAlchemy model."""

    def test_tablename(self) -> None:
        """ImageGenerationJob table should be named 'image_generation_jobs'."""
        assert ImageGenerationJob.__tablename__ == "image_generation_jobs"

    def test_default_status(self) -> None:
        """Default status should be PENDING."""
        status_column = ImageGenerationJob.__table__.columns["status"]
        assert status_column.default.arg == JobStatus.PENDING.value

    def test_default_attempts(self) -> None:
        """Default attempts should be 0."""
        attempts_column = ImageGenerationJob.__table__.columns["attempts"]
        assert attempts_column.default.arg == 0

    def test_required_fields(self) -> None:
        """Required fields should not be nullable."""
        required_fields = ["pet_id", "status", "attempts"]
        for field_name in required_fields:
            column = ImageGenerationJob.__table__.columns[field_name]
            assert column.nullable is False, f"{field_name} should not be nullable"

    def test_optional_fields(self) -> None:
        """Optional fields should be nullable."""
        optional_fields = ["stage", "started_at", "completed_at", "error"]
        for field_name in optional_fields:
            column = ImageGenerationJob.__table__.columns[field_name]
            assert column.nullable is True, f"{field_name} should be nullable"

    def test_primary_key(self) -> None:
        """id should be the primary key."""
        id_column = ImageGenerationJob.__table__.columns["id"]
        assert id_column.primary_key is True

    def test_foreign_key(self) -> None:
        """pet_id should reference pets.id."""
        pet_id_column = ImageGenerationJob.__table__.columns["pet_id"]
        fk = list(pet_id_column.foreign_keys)[0]
        assert str(fk.column) == "pets.id"

    def test_string_field_lengths(self) -> None:
        """String fields should have appropriate max lengths."""
        assert ImageGenerationJob.__table__.columns["status"].type.length == 20
        assert ImageGenerationJob.__table__.columns["stage"].type.length == 20
