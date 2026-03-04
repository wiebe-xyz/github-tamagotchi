"""GitHub webhook processing service."""

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.crud import pet as pet_crud
from github_tamagotchi.models.pet import PetMood, PetStage
from github_tamagotchi.services.pet_logic import get_next_stage

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


async def handle_push_event(payload: dict[str, Any], db: AsyncSession) -> str:
    """Handle push events - feed the pet and grant experience."""
    repo_info = _extract_repo_from_payload(payload)
    if not repo_info:
        return "no repository in payload"

    owner, name = repo_info
    pet = await pet_crud.get_pet_by_repo(db, owner, name)
    if not pet:
        return f"no pet found for {owner}/{name}"

    pet.health = min(100, pet.health + PUSH_HEALTH_BONUS)
    pet.experience = pet.experience + PUSH_EXPERIENCE_BONUS
    pet.last_fed_at = datetime.now(UTC)
    pet.mood = PetMood.HAPPY.value

    # Check for evolution
    current_stage = PetStage(pet.stage)
    new_stage = get_next_stage(current_stage, pet.experience)
    if new_stage != current_stage:
        pet.stage = new_stage.value
        logger.info(
            "pet_evolved_via_webhook",
            pet_id=pet.id,
            old_stage=current_stage.value,
            new_stage=new_stage.value,
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
    repo_info = _extract_repo_from_payload(payload)
    if not repo_info:
        return "no repository in payload"

    owner, name = repo_info
    pet = await pet_crud.get_pet_by_repo(db, owner, name)
    if not pet:
        return f"no pet found for {owner}/{name}"

    action = payload.get("action", "")

    if action == "opened":
        pet.mood = PetMood.WORRIED.value
        pet.experience = pet.experience + PR_OPENED_EXPERIENCE_BONUS
    elif action == "closed":
        pr = payload.get("pull_request", {})
        if pr.get("merged"):
            pet.mood = PetMood.HAPPY.value
            pet.health = min(100, pet.health + PR_MERGED_HEALTH_BONUS)
            pet.experience = pet.experience + PR_MERGED_EXPERIENCE_BONUS
        else:
            # PR closed without merge
            pet.mood = PetMood.CONTENT.value
    elif action == "reopened":
        pet.mood = PetMood.WORRIED.value

    # Check for evolution
    current_stage = PetStage(pet.stage)
    new_stage = get_next_stage(current_stage, pet.experience)
    if new_stage != current_stage:
        pet.stage = new_stage.value

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

    # Check for evolution
    current_stage = PetStage(pet.stage)
    new_stage = get_next_stage(current_stage, pet.experience)
    if new_stage != current_stage:
        pet.stage = new_stage.value

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

    if conclusion == "success":
        pet.health = min(100, pet.health + CI_SUCCESS_HEALTH_BONUS)
        pet.experience = pet.experience + CI_SUCCESS_EXPERIENCE_BONUS
        pet.mood = PetMood.DANCING.value
    elif conclusion in ("failure", "timed_out"):
        pet.health = max(0, pet.health + CI_FAILURE_HEALTH_PENALTY)
        pet.mood = PetMood.WORRIED.value

    # Check for evolution
    current_stage = PetStage(pet.stage)
    new_stage = get_next_stage(current_stage, pet.experience)
    if new_stage != current_stage:
        pet.stage = new_stage.value

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
