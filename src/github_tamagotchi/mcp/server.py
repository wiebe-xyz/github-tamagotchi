"""FastMCP server for GitHub Tamagotchi."""

from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from github_tamagotchi.core.database import async_session_factory
from github_tamagotchi.crud.milestone import create_milestone
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.pet_logic import (
    PetPersonality,
    calculate_experience,
    calculate_health_delta,
    calculate_mood,
    generate_personality,
    get_next_stage,
    get_personality_message,
)

mcp = FastMCP("GitHub Tamagotchi")


@mcp.tool()
async def check_pet_status(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Check the status of a pet for a GitHub repository.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Pet status including mood, health, and stage
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
        )
        pet = result.scalar_one_or_none()

        if not pet:
            return {
                "repo": f"{repo_owner}/{repo_name}",
                "error": "No pet found for this repository. Use register_pet to create one.",
            }

        github = GitHubService()
        health = await github.get_repo_health(repo_owner, repo_name)

        personality = _get_pet_personality(pet, repo_owner, repo_name)
        mood = PetMood(pet.mood)
        personality_msg = get_personality_message(pet.name, personality, mood)

        response: dict[str, Any] = {
            "repo": f"{repo_owner}/{repo_name}",
            "pet": {
                "name": pet.name,
                "stage": pet.stage,
                "mood": pet.mood,
                "health": pet.health,
                "experience": pet.experience,
                "created_at": pet.created_at.isoformat() if pet.created_at else None,
                "last_fed_at": pet.last_fed_at.isoformat() if pet.last_fed_at else None,
            },
            "personality": _format_personality(personality),
            "health_metrics": {
                "last_commit": health.last_commit_at.isoformat() if health.last_commit_at else None,
                "open_prs": health.open_prs_count,
                "open_issues": health.open_issues_count,
                "ci_passing": health.last_ci_success,
            },
        }
        if personality_msg:
            response["message"] = personality_msg
        return response


@mcp.tool()
async def register_pet(repo_owner: str, repo_name: str, name: str) -> dict[str, Any]:
    """Register a new pet for a GitHub repository.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository
        name: Name to give the pet

    Returns:
        The newly created pet details
    """
    async with async_session_factory() as session:
        personality = generate_personality(repo_owner, repo_name)
        pet = Pet(
            repo_owner=repo_owner,
            repo_name=repo_name,
            name=name,
            stage=PetStage.EGG.value,
            mood=PetMood.CONTENT.value,
            health=100,
            experience=0,
            personality_activity=personality.activity,
            personality_sociability=personality.sociability,
            personality_bravery=personality.bravery,
            personality_tidiness=personality.tidiness,
            personality_appetite=personality.appetite,
        )

        try:
            session.add(pet)
            await session.commit()
            await session.refresh(pet)
        except IntegrityError:
            await session.rollback()
            return {
                "repo": f"{repo_owner}/{repo_name}",
                "error": "A pet already exists for this repository.",
            }

        return {
            "repo": f"{repo_owner}/{repo_name}",
            "pet": {
                "id": pet.id,
                "name": pet.name,
                "stage": pet.stage,
                "mood": pet.mood,
                "health": pet.health,
                "experience": pet.experience,
            },
            "personality": _format_personality(personality),
            "message": f"Pet '{name}' has hatched as an egg!",
        }


@mcp.tool()
async def feed_pet(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Manually feed a pet (simulates activity).

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Updated pet status after feeding
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
        )
        pet = result.scalar_one_or_none()

        if not pet:
            return {
                "repo": f"{repo_owner}/{repo_name}",
                "error": "No pet found for this repository. Use register_pet to create one.",
            }

        old_health = pet.health
        old_stage = pet.stage

        pet.health = min(100, pet.health + 10)
        pet.experience += 5
        pet.last_fed_at = datetime.now(UTC)
        pet.mood = PetMood.HAPPY.value

        new_stage = get_next_stage(PetStage(pet.stage), pet.experience)
        evolved = new_stage.value != old_stage
        if evolved:
            pet.stage = new_stage.value
            await create_milestone(session, pet, old_stage, new_stage.value, pet.experience)

        await session.commit()

        response: dict[str, Any] = {
            "repo": f"{repo_owner}/{repo_name}",
            "action": "feed",
            "pet": {
                "name": pet.name,
                "stage": pet.stage,
                "mood": pet.mood,
                "health": pet.health,
                "experience": pet.experience,
            },
            "health_change": pet.health - old_health,
        }

        if evolved:
            response["evolution"] = f"Your pet evolved from {old_stage} to {new_stage.value}!"

        return response


@mcp.tool()
async def list_pets() -> dict[str, Any]:
    """List all registered pets.

    Returns:
        List of all pets and their current status
    """
    async with async_session_factory() as session:
        result = await session.execute(select(Pet))
        pets = result.scalars().all()

        return {
            "pets": [
                {
                    "id": pet.id,
                    "repo": f"{pet.repo_owner}/{pet.repo_name}",
                    "name": pet.name,
                    "stage": pet.stage,
                    "mood": pet.mood,
                    "health": pet.health,
                    "experience": pet.experience,
                }
                for pet in pets
            ],
            "count": len(pets),
        }


@mcp.tool()
async def get_pet_history(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Get the evolution history and stats for a pet.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Pet history including creation date, evolution stage, and stats
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
        )
        pet = result.scalar_one_or_none()

        if not pet:
            return {
                "repo": f"{repo_owner}/{repo_name}",
                "error": "No pet found for this repository. Use register_pet to create one.",
            }

        stages = list(PetStage)
        current_stage_idx = stages.index(PetStage(pet.stage))
        stages_completed = [s.value for s in stages[: current_stage_idx + 1]]
        stages_remaining = [s.value for s in stages[current_stage_idx + 1 :]]

        age_days = None
        if pet.created_at:
            created_at = pet.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - created_at).days

        return {
            "repo": f"{repo_owner}/{repo_name}",
            "pet": {
                "name": pet.name,
                "current_stage": pet.stage,
                "health": pet.health,
                "experience": pet.experience,
            },
            "evolution": {
                "stages_completed": stages_completed,
                "stages_remaining": stages_remaining,
                "progress_to_next": _calculate_stage_progress(pet.experience, pet.stage),
            },
            "history": {
                "created_at": pet.created_at.isoformat() if pet.created_at else None,
                "age_days": age_days,
                "last_fed_at": pet.last_fed_at.isoformat() if pet.last_fed_at else None,
                "last_checked_at": pet.last_checked_at.isoformat() if pet.last_checked_at else None,
            },
        }


@mcp.tool()
async def update_pet_from_repo(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Update a pet's status based on current repository health.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Updated pet status with changes from repo health check
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
        )
        pet = result.scalar_one_or_none()

        if not pet:
            return {
                "repo": f"{repo_owner}/{repo_name}",
                "error": "No pet found for this repository. Use register_pet to create one.",
            }

        github = GitHubService()
        health = await github.get_repo_health(repo_owner, repo_name)

        old_stage = pet.stage
        old_mood = pet.mood

        health_delta = calculate_health_delta(health)
        pet.health = max(0, min(100, pet.health + health_delta))

        exp_gained = calculate_experience(health)
        pet.experience += exp_gained

        new_mood = calculate_mood(health, pet.health)
        pet.mood = new_mood.value

        new_stage = get_next_stage(PetStage(pet.stage), pet.experience)
        evolved = new_stage.value != old_stage
        if evolved:
            pet.stage = new_stage.value
            await create_milestone(session, pet, old_stage, new_stage.value, pet.experience)

        pet.last_checked_at = datetime.now(UTC)

        await session.commit()

        personality = _get_pet_personality(pet, repo_owner, repo_name)
        personality_msg = get_personality_message(pet.name, personality, new_mood)

        update_response: dict[str, Any] = {
            "repo": f"{repo_owner}/{repo_name}",
            "pet": {
                "name": pet.name,
                "stage": pet.stage,
                "mood": pet.mood,
                "health": pet.health,
                "experience": pet.experience,
            },
            "changes": {
                "health_delta": health_delta,
                "experience_gained": exp_gained,
                "mood_changed": old_mood != pet.mood,
            },
        }

        if personality_msg:
            update_response["message"] = personality_msg

        if evolved:
            update_response["evolution"] = (
                f"Your pet evolved from {old_stage} to {new_stage.value}!"
            )

        return update_response


def _get_pet_personality(pet: Pet, repo_owner: str, repo_name: str) -> PetPersonality:
    """Get personality from pet DB fields, or generate if not yet set."""
    if pet.personality_activity is not None:
        return PetPersonality(
            activity=pet.personality_activity,
            sociability=pet.personality_sociability or 0.5,
            bravery=pet.personality_bravery or 0.5,
            tidiness=pet.personality_tidiness or 0.5,
            appetite=pet.personality_appetite or 0.5,
        )
    return generate_personality(repo_owner, repo_name)


def _format_personality(personality: PetPersonality) -> dict[str, Any]:
    """Format personality traits as a display-friendly dict."""
    return {
        "activity": personality.activity,
        "sociability": personality.sociability,
        "bravery": personality.bravery,
        "tidiness": personality.tidiness,
        "appetite": personality.appetite,
        "display": {
            "activity": "Active" if personality.activity >= 0.5 else "Lazy",
            "sociability": "Social" if personality.sociability >= 0.5 else "Shy",
            "bravery": "Brave" if personality.bravery >= 0.5 else "Cautious",
            "tidiness": "Neat" if personality.tidiness >= 0.5 else "Messy",
            "appetite": "Hungry" if personality.appetite >= 0.5 else "Light eater",
        },
    }


def _calculate_stage_progress(experience: int, current_stage: str) -> dict[str, Any]:
    """Calculate progress towards the next evolution stage."""
    from github_tamagotchi.services.pet_logic import EVOLUTION_THRESHOLDS

    stages = list(PetStage)
    current_idx = stages.index(PetStage(current_stage))

    if current_idx >= len(stages) - 1:
        return {"at_max_stage": True, "percentage": 100}

    next_stage = stages[current_idx + 1]
    current_threshold = EVOLUTION_THRESHOLDS[PetStage(current_stage)]
    next_threshold = EVOLUTION_THRESHOLDS[next_stage]

    progress = experience - current_threshold
    needed = next_threshold - current_threshold
    percentage = min(100, int((progress / needed) * 100)) if needed > 0 else 100

    return {
        "at_max_stage": False,
        "current_exp": experience,
        "next_stage": next_stage.value,
        "exp_needed": next_threshold,
        "percentage": percentage,
    }


def get_mcp_server() -> FastMCP:
    """Get the MCP server instance."""
    return mcp
