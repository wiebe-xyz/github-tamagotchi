"""Image generation queue service."""

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from github_tamagotchi.core.config import settings
from github_tamagotchi.core.telemetry import get_tracer
from github_tamagotchi.models.image_job import ImageGenerationJob, JobStatus
from github_tamagotchi.models.pet import Pet, PetStage
from github_tamagotchi.services.image_generation import ImageGenerationService, remove_background
from github_tamagotchi.services.openrouter import OpenRouterService
from github_tamagotchi.services.pet import update_canonical_appearance, update_images_generated_at
from github_tamagotchi.services.provider import ImageProvider
from github_tamagotchi.services.sprite_sheet import compose_animated_gif
from github_tamagotchi.services.storage import StorageService

_tracer = get_tracer(__name__)

logger = structlog.get_logger()

# Queue configuration
MAX_ATTEMPTS = 3
POLL_INTERVAL_SECONDS = 10


def get_image_provider() -> ImageProvider:
    """Get the configured image generation provider."""
    if settings.image_generation_provider == "comfyui":
        return ImageGenerationService()
    if settings.image_generation_provider == "openrouter":
        return OpenRouterService()
    raise ValueError(f"Unknown image provider: {settings.image_generation_provider}")


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
            select(func.count())
            .select_from(ImageGenerationJob)
            .where(ImageGenerationJob.status == status.value)
        )
        stats[status.value] = result.scalar() or 0

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

    Generates pet images via the configured provider for the specified stage
    (or all stages if None).

    Args:
        session: Database session
        job: The job to process
    """
    with _tracer.start_as_current_span("image_queue.process_job") as span:
        span.set_attribute("job.id", str(job.id))
        span.set_attribute("job.pet_id", str(job.pet_id))
        if job.stage:
            span.set_attribute("job.stage", job.stage)
        span.set_attribute("job.attempt", job.attempts + 1)

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

            # Generate images for each stage and upload to MinIO
            image_service = get_image_provider()
            storage = StorageService()
            style = getattr(pet, "style", "kawaii")
            use_sprite_sheets = settings.image_generation_provider == "openrouter"

            for stage in stages:
                logger.info(
                    "Generating image for stage",
                    job_id=job.id,
                    pet_id=job.pet_id,
                    stage=stage,
                )

                if use_sprite_sheets:
                    # Use sprite sheet generation for OpenRouter (produces 6 animation frames)
                    openrouter = OpenRouterService()
                    sheet_result = await openrouter.generate_sprite_sheet(
                        pet.repo_owner,
                        pet.repo_name,
                        stage,
                        style=style,
                        canonical_appearance=pet.canonical_appearance,
                    )

                    if sheet_result.success and sheet_result.sprite_sheet_data:
                        # Upload sprite sheet
                        await storage.upload_sprite_sheet(
                            pet.repo_owner, pet.repo_name, stage, sheet_result.sprite_sheet_data
                        )

                        # Upload individual frames
                        for idx, frame_bytes in enumerate(sheet_result.frames):
                            await storage.upload_frame(
                                pet.repo_owner, pet.repo_name, stage, idx, frame_bytes
                            )

                        # Compose and upload animated GIF
                        gif_data = compose_animated_gif(
                            sheet_result.frames,
                            mood=pet.mood if hasattr(pet, "mood") else "content",
                            health=pet.health if hasattr(pet, "health") else 100,
                        )
                        await storage.upload_animated_gif(
                            pet.repo_owner, pet.repo_name, stage, gif_data
                        )

                        # Update canonical appearance if not already set
                        if (
                            not pet.canonical_appearance
                            and sheet_result.canonical_appearance
                        ):
                            await update_canonical_appearance(
                                session,
                                pet.repo_owner,
                                pet.repo_name,
                                sheet_result.canonical_appearance,
                            )
                            pet.canonical_appearance = sheet_result.canonical_appearance

                        logger.info(
                            "Successfully generated and uploaded sprite sheet for stage",
                            job_id=job.id,
                            pet_id=job.pet_id,
                            stage=stage,
                            frame_count=len(sheet_result.frames),
                        )
                        continue

                    # Sprite sheet failed — fall back to single image generation
                    logger.warning(
                        "Sprite sheet generation failed, falling back to single image",
                        job_id=job.id,
                        stage=stage,
                        error=sheet_result.error,
                    )

                # Single image fallback (non-OpenRouter or sprite sheet failure)
                result = await image_service.generate_pet_image(
                    owner=pet.repo_owner,
                    repo=pet.repo_name,
                    stage=stage,
                    style=style,
                )

                if not result.success:
                    raise RuntimeError(
                        f"Image generation failed for stage {stage}: {result.error}"
                    )

                # Remove chroma-key background to produce a transparent PNG
                if result.image_data:
                    result.image_data = remove_background(result.image_data)
                    await storage.upload_image(
                        pet.repo_owner, pet.repo_name, stage, result.image_data
                    )

                logger.info(
                    "Successfully generated and uploaded image for stage",
                    job_id=job.id,
                    pet_id=job.pet_id,
                    stage=stage,
                )

            # Update the timestamp for when images were last generated
            await update_images_generated_at(session, pet.repo_owner, pet.repo_name)

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
