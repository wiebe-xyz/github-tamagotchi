"""Image generation queue service."""

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from github_tamagotchi.models.image_job import ImageGenerationJob, JobStatus
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.services.image_generation import ImageGenerationService

logger = structlog.get_logger()

# Queue configuration
MAX_ATTEMPTS = 3
POLL_INTERVAL_SECONDS = 10


async def create_job(
    session: AsyncSession,
    pet_id: int,
    stage: str | None = None,
) -> ImageGenerationJob:
    """Create a new image generation job for a pet.

    Args:
        session: Database session
        pet_id: ID of the pet to generate images for
        stage: Optional specific stage to generate (None = all stages)

    Returns:
        The created job
    """
    job = ImageGenerationJob(
        pet_id=pet_id,
        status=JobStatus.PENDING.value,
        stage=stage,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    logger.info("Created image generation job", job_id=job.id, pet_id=pet_id, stage=stage)
    return job


async def get_next_pending_job(session: AsyncSession) -> ImageGenerationJob | None:
    """Get the next pending job from the queue (FIFO).

    Args:
        session: Database session

    Returns:
        The next pending job, or None if queue is empty
    """
    result = await session.execute(
        select(ImageGenerationJob)
        .where(ImageGenerationJob.status == JobStatus.PENDING.value)
        .where(ImageGenerationJob.attempts < MAX_ATTEMPTS)
        .order_by(ImageGenerationJob.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def mark_job_processing(session: AsyncSession, job_id: int) -> None:
    """Mark a job as processing.

    Args:
        session: Database session
        job_id: ID of the job to update
    """
    await session.execute(
        update(ImageGenerationJob)
        .where(ImageGenerationJob.id == job_id)
        .values(
            status=JobStatus.PROCESSING.value,
            started_at=datetime.now(UTC),
            attempts=ImageGenerationJob.attempts + 1,
        )
    )
    await session.commit()
    logger.info("Job marked as processing", job_id=job_id)


async def mark_job_completed(session: AsyncSession, job_id: int) -> None:
    """Mark a job as completed.

    Args:
        session: Database session
        job_id: ID of the job to update
    """
    await session.execute(
        update(ImageGenerationJob)
        .where(ImageGenerationJob.id == job_id)
        .values(
            status=JobStatus.COMPLETED.value,
            completed_at=datetime.now(UTC),
            error=None,
        )
    )
    await session.commit()
    logger.info("Job marked as completed", job_id=job_id)


async def mark_job_failed(
    session: AsyncSession,
    job_id: int,
    error: str,
    attempts: int,
) -> None:
    """Mark a job as failed.

    If attempts < MAX_ATTEMPTS, resets status to pending for retry.

    Args:
        session: Database session
        job_id: ID of the job to update
        error: Error message
        attempts: Current attempt count
    """
    if attempts < MAX_ATTEMPTS:
        # Reset to pending for retry
        new_status = JobStatus.PENDING.value
        logger.warning(
            "Job failed, will retry",
            job_id=job_id,
            attempts=attempts,
            max_attempts=MAX_ATTEMPTS,
            error=error,
        )
    else:
        # Max attempts reached, mark as failed
        new_status = JobStatus.FAILED.value
        logger.error(
            "Job failed permanently",
            job_id=job_id,
            attempts=attempts,
            error=error,
        )

    await session.execute(
        update(ImageGenerationJob)
        .where(ImageGenerationJob.id == job_id)
        .values(
            status=new_status,
            error=error,
        )
    )
    await session.commit()


async def get_job_by_id(session: AsyncSession, job_id: int) -> ImageGenerationJob | None:
    """Get a job by ID.

    Args:
        session: Database session
        job_id: ID of the job

    Returns:
        The job, or None if not found
    """
    result = await session.execute(
        select(ImageGenerationJob).where(ImageGenerationJob.id == job_id)
    )
    return result.scalar_one_or_none()


async def get_jobs_by_pet_id(
    session: AsyncSession,
    pet_id: int,
) -> list[ImageGenerationJob]:
    """Get all jobs for a specific pet.

    Args:
        session: Database session
        pet_id: ID of the pet

    Returns:
        List of jobs for the pet
    """
    result = await session.execute(
        select(ImageGenerationJob)
        .where(ImageGenerationJob.pet_id == pet_id)
        .order_by(ImageGenerationJob.created_at.desc())
    )
    return list(result.scalars().all())


async def get_queue_stats(session: AsyncSession) -> dict[str, int]:
    """Get queue statistics.

    Args:
        session: Database session

    Returns:
        Dictionary with queue stats (pending, processing, completed, failed counts)
    """
    stats: dict[str, int] = {}

    for status in JobStatus:
        result = await session.execute(
            select(ImageGenerationJob).where(
                ImageGenerationJob.status == status.value
            )
        )
        stats[status.value] = len(result.scalars().all())

    return stats


async def get_pet_by_id(session: AsyncSession, pet_id: int) -> Pet | None:
    """Get a pet by ID.

    Args:
        session: Database session
        pet_id: ID of the pet

    Returns:
        The pet, or None if not found
    """
    result = await session.execute(select(Pet).where(Pet.id == pet_id))
    return result.scalar_one_or_none()


async def process_job(session: AsyncSession, job: ImageGenerationJob) -> None:
    """Process a single image generation job.

    Generates pet images via ComfyUI for the specified stage (or all stages if None).

    Args:
        session: Database session
        job: The job to process
    """
    logger.info(
        "Processing image generation job",
        job_id=job.id,
        pet_id=job.pet_id,
        stage=job.stage,
        attempt=job.attempts + 1,
    )

    await mark_job_processing(session, job.id)

    try:
        # Fetch the pet to get owner/repo info
        pet = await get_pet_by_id(session, job.pet_id)
        if not pet:
            raise ValueError(f"Pet with id {job.pet_id} not found")

        # Determine which stages to generate (specific stage or all stages)
        stages = [job.stage] if job.stage else [stage.value for stage in PetStage]

        # Generate images for each stage
        image_service = ImageGenerationService()
        for stage in stages:
            logger.info(
                "Generating image for stage",
                job_id=job.id,
                pet_id=job.pet_id,
                stage=stage,
            )

            result = await image_service.generate_pet_image(
                owner=pet.repo_owner,
                repo=pet.repo_name,
                stage=stage,
            )

            if not result.success:
                raise RuntimeError(
                    f"Image generation failed for stage {stage}: {result.error}"
                )

            logger.info(
                "Successfully generated image for stage",
                job_id=job.id,
                pet_id=job.pet_id,
                stage=stage,
                filename=result.filename,
            )

            # NOTE: Image storage to MinIO will be implemented separately.
            # For now, ComfyUI saves images to its output directory.
            # The badge endpoint can serve from there or use a fallback.

        await mark_job_completed(session, job.id)
        logger.info(
            "Successfully processed job",
            job_id=job.id,
            pet_id=job.pet_id,
            stages_generated=stages,
        )

    except Exception as e:
        error_msg = str(e)
        # Re-fetch job to get current attempts count
        updated_job = await get_job_by_id(session, job.id)
        if updated_job:
            await mark_job_failed(session, job.id, error_msg, updated_job.attempts)
        raise


async def run_worker(
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event | None = None,
    poll_interval: float | None = None,
) -> None:
    """Run the image generation queue worker.

    Continuously polls for pending jobs and processes them.

    Args:
        session_factory: Factory for creating database sessions
        stop_event: Optional event to signal worker shutdown
        poll_interval: Optional poll interval override (defaults to POLL_INTERVAL_SECONDS)
    """
    interval = poll_interval if poll_interval is not None else POLL_INTERVAL_SECONDS
    logger.info("Starting image generation queue worker")

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Worker shutdown requested")
            break

        try:
            async with session_factory() as session:
                job = await get_next_pending_job(session)

                if job:
                    await process_job(session, job)
                else:
                    # No pending jobs, wait before polling again
                    await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info("Worker cancelled")
            break
        except Exception:
            logger.exception("Error in queue worker, continuing...")
            await asyncio.sleep(interval)
