"""GitHub webhook processing service."""

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.crud.contributor_relationship import apply_score_delta
from github_tamagotchi.crud.milestone import create_milestone
from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.pet_logic import get_next_stage

from github_tamagotchi.core.telemetry import get_tracer

_tracer = get_tracer(__name__)

logger = structlog.get_logger()

# Experience and health rewards for webhook events
PUSH_HEALTH_BONUS = 10
PUSH_EXPERIENCE_BONUS = 20
CI_SUCCESS_HEALTH_BONUS = 5
CI_SUCCESS_EXPERIENCE_BONUS = 10
CI_FAILURE_HEALTH_PENALTY = -5
PR_OPENED_EXPERIENCE_BONUS = 5
PR_MERGED_HEALTH_BONUS = 5
PR_MERGED_EXPERIENCE_BONUS = 15
ISSUE_OPENED_EXPERIENCE_BONUS = 3


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook signature (SHA-256).

    GitHub sends a signature in the X-Hub-Signature-256 header as
    'sha256=<hex_digest>'. We compute the HMAC-SHA256 of the raw body
    using the webhook secret and compare.
    """
    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(f"sha256={expected}", signature)


def _extract_repo_from_payload(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Extract repo_owner and repo_name from webhook payload."""
    repository = payload.get("repository")
    if not repository:
        return None

    owner_info = repository.get("owner", {})
    owner = owner_info.get("login")
    name = repository.get("name")

    if not owner or not name:
        return None

    return (owner, name)


async def _apply_evolution(
    pet: Any, db: AsyncSession
) -> tuple[str, str] | None:
    """Check for evolution and apply stage change + milestone if needed.

    Returns (old_stage, new_stage) if evolution occurred, else None.
    """
    current_stage = PetStage(pet.stage)
    new_stage = get_next_stage(current_stage, pet.experience)
    if new_stage == current_stage:
        return None
    pet.stage = new_stage.value
    await create_milestone(db, pet, current_stage.value, new_stage.value, pet.experience)
    return (current_stage.value, new_stage.value)


async def handle_push_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle push events - feed the pet and grant experience."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.push") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        now = datetime.now(UTC)
        pet.health = min(100, pet.health + PUSH_HEALTH_BONUS)
        pet.experience = pet.experience + PUSH_EXPERIENCE_BONUS
        pet.last_fed_at = now
        pet.mood = PetMood.HAPPY.value

        evolution = await _apply_evolution(pet, db)
        if evolution:
            logger.info(
                "pet_evolved_via_webhook",
                pet_id=pet.id,
                old_stage=evolution[0],
                new_stage=evolution[1],
            )

        # Update contributor score for the pusher
        pusher = payload.get("pusher", {}).get("name") or payload.get("sender", {}).get("login")
        if pusher:
            await apply_score_delta(
                db=db,
                pet_id=pet.id,
                github_username=pusher,
                delta=5,  # SCORE_PER_COMMIT
                event_description="pushed commits",
                now=now,
            )

        await db.commit()

        logger.info(
            "webhook_push_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            new_health=pet.health,
            new_experience=pet.experience,
        )
        return f"push processed for {owner}/{name}"


async def handle_pull_request_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle pull_request events - affect mood based on action."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.pull_request") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        action = payload.get("action", "")
        now = datetime.now(UTC)

        if action == "opened":
            pet.mood = PetMood.WORRIED.value
            pet.experience = pet.experience + PR_OPENED_EXPERIENCE_BONUS
        elif action == "closed":
            pr = payload.get("pull_request", {})
            if pr.get("merged"):
                pet.mood = PetMood.HAPPY.value
                pet.health = min(100, pet.health + PR_MERGED_HEALTH_BONUS)
                pet.experience = pet.experience + PR_MERGED_EXPERIENCE_BONUS
                # Credit the merger in contributor relationships
                merged_by = (pr.get("merged_by") or {}).get("login")
                if merged_by:
                    await apply_score_delta(
                        db=db,
                        pet_id=pet.id,
                        github_username=merged_by,
                        delta=10,  # SCORE_PER_MERGED_PR
                        event_description="merged a PR",
                        now=now,
                    )
            else:
                # PR closed without merge
                pet.mood = PetMood.CONTENT.value
        elif action == "reopened":
            pet.mood = PetMood.WORRIED.value

        await _apply_evolution(pet, db)

        await db.commit()

        logger.info(
            "webhook_pr_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            action=action,
            new_mood=pet.mood,
        )
        return f"pull_request ({action}) processed for {owner}/{name}"


async def handle_issues_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle issues events - lonely state for new issues."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.issues") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        action = payload.get("action", "")

        if action == "opened":
            pet.mood = PetMood.LONELY.value
            pet.experience = pet.experience + ISSUE_OPENED_EXPERIENCE_BONUS
        elif action == "closed":
            pet.mood = PetMood.HAPPY.value

        await _apply_evolution(pet, db)

        await db.commit()

        logger.info(
            "webhook_issue_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            action=action,
            new_mood=pet.mood,
        )
        return f"issues ({action}) processed for {owner}/{name}"


async def handle_check_run_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle check_run events - CI status affects health and mood."""
    repo = payload.get("repository", {}).get("full_name", "unknown")
    with _tracer.start_as_current_span("webhook.check_run") as span:
        span.set_attribute("webhook.repo", repo)

        repo_info = _extract_repo_from_payload(payload)
        if not repo_info:
            return "no repository in payload"

        owner, name = repo_info
        pet = await pet_crud.get_pet_by_repo(db, owner, name)
        if not pet:
            return f"no pet found for {owner}/{name}"

        action = payload.get("action", "")
        if action != "completed":
            return f"check_run ({action}) ignored for {owner}/{name}"

        check_run = payload.get("check_run", {})
        conclusion = check_run.get("conclusion", "")
        now = datetime.now(UTC)

        if conclusion == "success":
            pet.health = min(100, pet.health + CI_SUCCESS_HEALTH_BONUS)
            pet.experience = pet.experience + CI_SUCCESS_EXPERIENCE_BONUS
            pet.mood = PetMood.DANCING.value
        elif conclusion in ("failure", "timed_out"):
            pet.health = max(0, pet.health + CI_FAILURE_HEALTH_PENALTY)
            pet.mood = PetMood.WORRIED.value
            # Penalise the person who triggered the failing check
            sender = payload.get("sender", {}).get("login")
            if sender:
                await apply_score_delta(
                    db=db,
                    pet_id=pet.id,
                    github_username=sender,
                    delta=-20,
                    event_description="broke CI",
                    now=now,
                )

        await _apply_evolution(pet, db)

        await db.commit()

        logger.info(
            "webhook_check_run_processed",
            repo=f"{owner}/{name}",
            pet_id=pet.id,
            conclusion=conclusion,
            new_health=pet.health,
            new_mood=pet.mood,
        )
        return f"check_run ({conclusion}) processed for {owner}/{name}"


EVENT_HANDLERS: dict[str, Any] = {
    "push": handle_push_event,
    "pull_request": handle_pull_request_event,
    "issues": handle_issues_event,
    "check_run": handle_check_run_event,
}
