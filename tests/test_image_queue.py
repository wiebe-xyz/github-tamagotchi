"""Tests for image generation queue service."""

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from github_tamagotchi.models.image_job import JobStatus
from github_tamagotchi.models.pet import Base, Pet, PetMood, PetStage
from github_tamagotchi.services import image_queue
from github_tamagotchi.services.image_generation import GenerationResult

# Use SQLite for testing (in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

queue_test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
)

queue_test_session_factory = async_sessionmaker(
    queue_test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="module", autouse=True)
async def cleanup_queue_test_engine() -> AsyncIterator[None]:
    """Cleanup queue test engine after all tests in this module."""
    yield
    await queue_test_engine.dispose()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Create test database tables and provide a session."""
    async with queue_test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with queue_test_session_factory() as session:
        yield session

    async with queue_test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def test_pet(db_session: AsyncSession) -> Pet:
    """Create a test pet for job tests."""
    pet = Pet(
        repo_owner="test-owner",
        repo_name="test-repo",
        name="Test Pet",
        stage=PetStage.EGG.value,
        mood=PetMood.CONTENT.value,
    )
    db_session.add(pet)
    await db_session.commit()
    await db_session.refresh(pet)
    return pet


class TestCreateJob:
    """Tests for create_job function."""

    async def test_create_job_success(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should create a pending job for a pet."""
        job = await image_queue.create_job(db_session, test_pet.id)

        assert job.id is not None
        assert job.pet_id == test_pet.id
        assert job.status == JobStatus.PENDING.value
        assert job.stage is None
        assert job.attempts == 0
        assert job.error is None
        assert job.created_at is not None

    async def test_create_job_with_stage(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should create a job with specific stage."""
        job = await image_queue.create_job(db_session, test_pet.id, stage="baby")

        assert job.stage == "baby"

    async def test_create_multiple_jobs(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should create multiple jobs for the same pet."""
        job1 = await image_queue.create_job(db_session, test_pet.id)
        job2 = await image_queue.create_job(db_session, test_pet.id)

        assert job1.id != job2.id
        assert job1.pet_id == job2.pet_id == test_pet.id


class TestGetNextPendingJob:
    """Tests for get_next_pending_job function."""

    async def test_empty_queue(self, db_session: AsyncSession) -> None:
        """Should return None when queue is empty."""
        job = await image_queue.get_next_pending_job(db_session)
        assert job is None

    async def test_get_pending_job(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should return the first pending job."""
        created_job = await image_queue.create_job(db_session, test_pet.id)

        job = await image_queue.get_next_pending_job(db_session)

        assert job is not None
        assert job.id == created_job.id

    async def test_fifo_order(self, db_session: AsyncSession, test_pet: Pet) -> None:
        """Should return jobs in FIFO order."""
        job1 = await image_queue.create_job(db_session, test_pet.id, stage="first")
        await image_queue.create_job(db_session, test_pet.id, stage="second")

        next_job = await image_queue.get_next_pending_job(db_session)

        assert next_job is not None
        assert next_job.id == job1.id
        assert next_job.stage == "first"

    async def test_skip_processing_jobs(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should not return jobs that are already processing."""
        job = await image_queue.create_job(db_session, test_pet.id)
        await image_queue.mark_job_processing(db_session, job.id)

        next_job = await image_queue.get_next_pending_job(db_session)

        assert next_job is None

    async def test_skip_max_attempts(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should not return jobs that have reached max attempts."""
        job = await image_queue.create_job(db_session, test_pet.id)

        # Manually set attempts to max
        job.attempts = image_queue.MAX_ATTEMPTS
        await db_session.commit()

        next_job = await image_queue.get_next_pending_job(db_session)

        assert next_job is None


class TestMarkJobProcessing:
    """Tests for mark_job_processing function."""

    async def test_mark_processing(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should update job status to processing."""
        job = await image_queue.create_job(db_session, test_pet.id)

        await image_queue.mark_job_processing(db_session, job.id)

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.PROCESSING.value
        assert updated_job.started_at is not None
        assert updated_job.attempts == 1

    async def test_increment_attempts(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should increment attempts each time."""
        job = await image_queue.create_job(db_session, test_pet.id)

        await image_queue.mark_job_processing(db_session, job.id)

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        assert updated_job.attempts == 1


class TestMarkJobCompleted:
    """Tests for mark_job_completed function."""

    async def test_mark_completed(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should update job status to completed."""
        job = await image_queue.create_job(db_session, test_pet.id)
        await image_queue.mark_job_processing(db_session, job.id)

        await image_queue.mark_job_completed(db_session, job.id)

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.COMPLETED.value
        assert updated_job.completed_at is not None
        assert updated_job.error is None


class TestMarkJobFailed:
    """Tests for mark_job_failed function."""

    async def test_mark_failed_with_retry(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should reset to pending if attempts < max."""
        job = await image_queue.create_job(db_session, test_pet.id)
        await image_queue.mark_job_processing(db_session, job.id)

        await image_queue.mark_job_failed(
            db_session, job.id, "Test error", attempts=1
        )

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.PENDING.value
        assert updated_job.error == "Test error"

    async def test_mark_failed_permanently(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should mark as failed when max attempts reached."""
        job = await image_queue.create_job(db_session, test_pet.id)
        await image_queue.mark_job_processing(db_session, job.id)

        await image_queue.mark_job_failed(
            db_session, job.id, "Final error", attempts=image_queue.MAX_ATTEMPTS
        )

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.FAILED.value
        assert updated_job.error == "Final error"


class TestGetJobsByPetId:
    """Tests for get_jobs_by_pet_id function."""

    async def test_get_jobs_for_pet(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should return all jobs for a pet."""
        await image_queue.create_job(db_session, test_pet.id, stage="egg")
        await image_queue.create_job(db_session, test_pet.id, stage="baby")

        jobs = await image_queue.get_jobs_by_pet_id(db_session, test_pet.id)

        assert len(jobs) == 2

    async def test_no_jobs_for_pet(self, db_session: AsyncSession) -> None:
        """Should return empty list when no jobs exist."""
        jobs = await image_queue.get_jobs_by_pet_id(db_session, 999)

        assert jobs == []


class TestGetQueueStats:
    """Tests for get_queue_stats function."""

    async def test_empty_queue_stats(self, db_session: AsyncSession) -> None:
        """Should return all zeros for empty queue."""
        stats = await image_queue.get_queue_stats(db_session)

        assert stats["pending"] == 0
        assert stats["processing"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0

    async def test_queue_stats_with_jobs(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should return correct counts for each status."""
        # Create jobs in different states
        job1 = await image_queue.create_job(db_session, test_pet.id)
        job2 = await image_queue.create_job(db_session, test_pet.id)
        await image_queue.create_job(db_session, test_pet.id)

        await image_queue.mark_job_processing(db_session, job1.id)
        await image_queue.mark_job_completed(db_session, job1.id)

        await image_queue.mark_job_processing(db_session, job2.id)

        stats = await image_queue.get_queue_stats(db_session)

        assert stats["pending"] == 1
        assert stats["processing"] == 1
        assert stats["completed"] == 1
        assert stats["failed"] == 0


class TestProcessJob:
    """Tests for process_job function."""

    async def test_process_job_success(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should process a job successfully when image generation succeeds."""
        job = await image_queue.create_job(db_session, test_pet.id)

        # Mock the image generation service to return success
        mock_result = GenerationResult(
            success=True,
            image_data=b"fake_image_data",
            filename="test_image.png",
        )

        with patch(
            "github_tamagotchi.services.image_queue.ImageGenerationService"
        ) as mock_service_class:
            mock_service = AsyncMock()
            mock_service.generate_pet_image.return_value = mock_result
            mock_service_class.return_value = mock_service

            await image_queue.process_job(db_session, job)

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.COMPLETED.value

    async def test_process_job_with_specific_stage(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should only generate image for the specified stage."""
        job = await image_queue.create_job(db_session, test_pet.id, stage="baby")

        mock_result = GenerationResult(
            success=True,
            image_data=b"fake_image_data",
            filename="test_image.png",
        )

        with patch(
            "github_tamagotchi.services.image_queue.ImageGenerationService"
        ) as mock_service_class:
            mock_service = AsyncMock()
            mock_service.generate_pet_image.return_value = mock_result
            mock_service_class.return_value = mock_service

            await image_queue.process_job(db_session, job)

            # Should be called only once for the specific stage
            assert mock_service.generate_pet_image.call_count == 1
            call_args = mock_service.generate_pet_image.call_args
            assert call_args.kwargs["stage"] == "baby"

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.COMPLETED.value

    async def test_process_job_all_stages(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should generate images for all stages when stage is None."""
        job = await image_queue.create_job(db_session, test_pet.id)  # stage=None

        mock_result = GenerationResult(
            success=True,
            image_data=b"fake_image_data",
            filename="test_image.png",
        )

        with patch(
            "github_tamagotchi.services.image_queue.ImageGenerationService"
        ) as mock_service_class:
            mock_service = AsyncMock()
            mock_service.generate_pet_image.return_value = mock_result
            mock_service_class.return_value = mock_service

            await image_queue.process_job(db_session, job)

            # Should be called 6 times (once for each stage)
            assert mock_service.generate_pet_image.call_count == 6

    async def test_process_job_failure(
        self, db_session: AsyncSession, test_pet: Pet
    ) -> None:
        """Should mark job as failed when image generation fails."""
        job = await image_queue.create_job(db_session, test_pet.id, stage="egg")

        mock_result = GenerationResult(
            success=False,
            error="ComfyUI connection failed",
        )

        with patch(
            "github_tamagotchi.services.image_queue.ImageGenerationService"
        ) as mock_service_class:
            mock_service = AsyncMock()
            mock_service.generate_pet_image.return_value = mock_result
            mock_service_class.return_value = mock_service

            with pytest.raises(RuntimeError, match="Image generation failed"):
                await image_queue.process_job(db_session, job)

        updated_job = await image_queue.get_job_by_id(db_session, job.id)
        assert updated_job is not None
        # Should be pending for retry (attempts=1 < MAX_ATTEMPTS=3)
        assert updated_job.status == JobStatus.PENDING.value
        assert "ComfyUI connection failed" in str(updated_job.error)

    async def test_process_job_pet_not_found(
        self, db_session: AsyncSession
    ) -> None:
        """Should fail when pet is not found."""
        # Create a job for a non-existent pet by directly inserting
        from github_tamagotchi.models.image_job import ImageGenerationJob

        job = ImageGenerationJob(
            pet_id=99999,  # Non-existent pet
            status=JobStatus.PENDING.value,
        )
        db_session.add(job)
        await db_session.commit()
        await db_session.refresh(job)

        with pytest.raises(ValueError, match="Pet with id 99999 not found"):
            await image_queue.process_job(db_session, job)


class TestRunWorker:
    """Tests for run_worker function."""

    async def test_worker_processes_job(self, test_pet: Pet) -> None:
        """Should process pending jobs."""
        # Set up fresh database for this test
        async with queue_test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Create a pet and job
        async with queue_test_session_factory() as session:
            pet = Pet(
                repo_owner="worker-test",
                repo_name="worker-repo",
                name="Worker Pet",
            )
            session.add(pet)
            await session.commit()
            await session.refresh(pet)

            await image_queue.create_job(session, pet.id, stage="egg")  # Single stage for speed

        # Mock the image generation service
        mock_result = GenerationResult(
            success=True,
            image_data=b"fake_image_data",
            filename="test_image.png",
        )

        # Run worker briefly with mocked image service
        stop_event = asyncio.Event()

        async def stop_after_processing() -> None:
            await asyncio.sleep(0.5)
            stop_event.set()

        with patch(
            "github_tamagotchi.services.image_queue.ImageGenerationService"
        ) as mock_service_class:
            mock_service = AsyncMock()
            mock_service.generate_pet_image.return_value = mock_result
            mock_service_class.return_value = mock_service

            await asyncio.gather(
                image_queue.run_worker(
                    queue_test_session_factory, stop_event, poll_interval=0.1
                ),
                stop_after_processing(),
            )

        # Check job was processed
        async with queue_test_session_factory() as session:
            stats = await image_queue.get_queue_stats(session)
            assert stats["completed"] == 1
            assert stats["pending"] == 0

        # Cleanup
        async with queue_test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def test_worker_stops_on_event(self) -> None:
        """Should stop when stop event is set."""
        async with queue_test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        stop_event = asyncio.Event()
        stop_event.set()

        # Should exit immediately
        await asyncio.wait_for(
            image_queue.run_worker(queue_test_session_factory, stop_event, poll_interval=0.1),
            timeout=1.0,
        )

        async with queue_test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
