"""FastMCP server for GitHub Tamagotchi.

Bearer-token authenticated (generate a token from the dashboard first — see
services/mcp_auth.py). Every tool here is scoped to the calling user: you
can create, feed, play with, and check on your own pets, and see aggregate
leaderboard standings, but you cannot read or mutate anyone else's pet.
"""

from datetime import UTC, datetime
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import github_tamagotchi.api.routes as _api_routes
from github_tamagotchi.api.auth import _verify_github_repo_access
from github_tamagotchi.core.database import async_session_factory
from github_tamagotchi.crud.milestone import create_milestone
from github_tamagotchi.models.pet import Pet, PetMood, PetStage
from github_tamagotchi.models.user import User
from github_tamagotchi.services.ascii_render import render_pet_ascii
from github_tamagotchi.services.github import GitHubService
from github_tamagotchi.services.mcp_auth import McpTokenVerifier
from github_tamagotchi.services.naming import is_valid_repo_identifier
from github_tamagotchi.services.pet_feeding import (
    apply_exercise_decay,
    apply_feed,
    weight_label,
)
from github_tamagotchi.services.pet_logic import (
    PetPersonality,
    calculate_experience,
    calculate_health_delta,
    calculate_mood,
    generate_personality,
    get_next_stage,
    get_personality_message,
)
from github_tamagotchi.services.token_encryption import decrypt_token

INSTRUCTIONS = """\
GitHub Tamagotchi: a virtual pet whose life is driven by a real GitHub \
repository's activity — commits, CI runs, PR age, security alerts. You are \
the pet's caretaker on behalf of the authenticated user; every tool here \
acts on their pets only.

How the game works:
- Health, XP, and evolution stage (Egg -> Baby -> Child -> Teen -> Adult -> \
Elder) come ONLY from real repo activity, applied via update_pet_from_repo. \
There is no way to manually inflate them — that's deliberate.
- feed_pet is a separate, freely-callable action for fun, not progress: it \
gives a small health/mood bump and raises the pet's weight. Feed it too \
often without matching real activity and it gets chubby, then fat — an \
already-fat pet gets no benefit from being fed again until it works some of \
that off. update_pet_from_repo (real activity) is what burns weight back \
down, so an actively-worked-on repo's pet stays trim no matter how often \
you feed it.
- play_with_pet is a lightweight "someone checked in" action: it nudges \
mood one step happier (capped below the special "dancing" mood, which is \
reserved for a real health win) and is rate-limited to prevent spamming it \
for infinite happiness.
- check_pet_status and play_with_pet both return an ASCII rendering of the \
pet's current appearance so you can actually show the user how their pet \
looks, not just report numbers.

Rules: every tool that touches a specific pet requires you to own it — \
trying to read or change someone else's pet returns a clear error, not \
their data. get_leaderboard is the one exception: it shows the same \
aggregate standings (name, stage, health, rank) already public on the \
website, for comparing against your own pets.

Call how_to_play() any time for this text again.\
"""


mcp = FastMCP("GitHub Tamagotchi", instructions=INSTRUCTIONS, auth=McpTokenVerifier())

# Rate limit for play_with_pet's mood nudge, keyed by pet id. In-process only
# (fine for a single-instance toy deployment) — resets on restart.
_PLAY_COOLDOWN = 3600  # seconds
_last_played_at: dict[int, float] = {}


def _current_user_id() -> int:
    """Resolve the authenticated caller's user id, or raise.

    FastMCP's auth layer already rejects requests with no/invalid bearer
    token before a tool body ever runs — this only fires if something calls
    a tool outside of a real request context (shouldn't happen in practice).
    """
    access_token = get_access_token()
    if access_token is None:
        raise ToolError("Not authenticated. Generate an MCP token from the dashboard first.")
    user_id = access_token.claims.get("user_id")
    if user_id is None:
        raise ToolError("Not authenticated.")
    return int(user_id)


async def _get_owned_pet(session: AsyncSession, repo_owner: str, repo_name: str) -> Pet:
    """Fetch a pet, raising unless it belongs to the authenticated caller."""
    user_id = _current_user_id()
    result = await session.execute(
        select(Pet).where(Pet.repo_owner == repo_owner, Pet.repo_name == repo_name)
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise ToolError(
            f"No pet found for {repo_owner}/{repo_name}. Use register_pet to create one."
        )
    if pet.user_id != user_id:
        raise ToolError("That pet doesn't belong to you.")
    return pet


@mcp.tool()
def how_to_play() -> str:
    """Explain how GitHub Tamagotchi works — the rules, and what each tool does."""
    return INSTRUCTIONS


@mcp.tool()
async def check_pet_status(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Check the status of one of your pets, including an ASCII drawing of it.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Pet status including mood, health, weight, and an ASCII rendering
    """
    async with async_session_factory() as session:
        pet = await _get_owned_pet(session, repo_owner, repo_name)

        github = GitHubService()
        health = await github.get_repo_health(repo_owner, repo_name)

        personality = _get_pet_personality(pet, repo_owner, repo_name)
        mood = PetMood(pet.mood)
        personality_msg = get_personality_message(pet.name, personality, mood)
        ascii_art = await render_pet_ascii(pet, _try_storage())

        response: dict[str, Any] = {
            "repo": f"{repo_owner}/{repo_name}",
            "pet": {
                "name": pet.name,
                "stage": pet.stage,
                "mood": pet.mood,
                "health": pet.health,
                "experience": pet.experience,
                "weight": weight_label(pet.weight),
                "created_at": pet.created_at.isoformat() if pet.created_at else None,
                "last_fed_at": pet.last_fed_at.isoformat() if pet.last_fed_at else None,
            },
            "ascii_art": ascii_art,
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
    """Register a new pet for a GitHub repository you have access to.

    Verifies you can actually see the repository on GitHub before creating
    the pet, using the GitHub token from your dashboard login.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository
        name: Name to give the pet

    Returns:
        The newly created pet details
    """
    if not is_valid_repo_identifier(repo_owner, repo_name):
        return {
            "repo": f"{repo_owner}/{repo_name}",
            "error": "repo_owner/repo_name must be valid GitHub identifiers.",
        }

    user_id = _current_user_id()

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if user is None or not user.encrypted_token:
            raise ToolError(
                "Your account has no linked GitHub access token — log in via the "
                "website first (register_pet needs to verify repo access)."
            )
        access_token = decrypt_token(user.encrypted_token)
        if not await _verify_github_repo_access(access_token, repo_owner, repo_name):
            raise ToolError(
                f"You don't have access to {repo_owner}/{repo_name} on GitHub, "
                "or it doesn't exist."
            )

        personality = generate_personality(repo_owner, repo_name)
        pet = Pet(
            repo_owner=repo_owner,
            repo_name=repo_name,
            name=name,
            user_id=user_id,
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
    """Feed one of your pets a snack.

    Freely callable, but overusing it makes the pet fat rather than
    stronger — health/XP progress only ever comes from real repo activity
    (see update_pet_from_repo). An already-fat pet gets nothing from being
    fed again until real activity works some of that weight back off.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Updated pet status after feeding
    """
    async with async_session_factory() as session:
        pet = await _get_owned_pet(session, repo_owner, repo_name)

        old_stage = pet.stage
        result = apply_feed(pet)

        pet.last_fed_at = datetime.now(UTC)

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
                "weight": weight_label(pet.weight),
            },
            "health_change": result.health_change,
            "overfed": result.overfed,
            "message": result.message,
        }
        if evolved:
            response["evolution"] = f"Your pet evolved from {old_stage} to {new_stage.value}!"
        return response


@mcp.tool()
async def play_with_pet(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Check in on one of your pets — shows its ASCII drawing and cheers it up.

    A little attention makes the pet happier (one mood step, capped below
    the special "dancing" mood which is reserved for a real health win).
    Rate-limited per pet so checking in repeatedly doesn't game happiness.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        The pet's ASCII drawing and whether checking in cheered it up
    """
    import time

    from github_tamagotchi.services.pet_feeding import nudge_mood_happier

    async with async_session_factory() as session:
        pet = await _get_owned_pet(session, repo_owner, repo_name)

        now = time.monotonic()
        # time.monotonic()'s reference point is unspecified (often since boot
        # or container start) — on a freshly started process it can itself be
        # well under _PLAY_COOLDOWN, so a missing entry must default to
        # "definitely not on cooldown" (-inf), not 0.0. Defaulting to 0.0
        # would make `now - 0.0 < _PLAY_COOLDOWN` true for the first hour
        # after every restart, incorrectly blocking every pet's first ever
        # play_with_pet call.
        last = _last_played_at.get(pet.id, float("-inf"))
        on_cooldown = (now - last) < _PLAY_COOLDOWN

        mood_changed = False
        if not on_cooldown:
            mood_changed = nudge_mood_happier(pet)
            _last_played_at[pet.id] = now
            await session.commit()

        ascii_art = await render_pet_ascii(pet, _try_storage())
        personality = _get_pet_personality(pet, repo_owner, repo_name)
        message = get_personality_message(pet.name, personality, PetMood(pet.mood))

        response: dict[str, Any] = {
            "repo": f"{repo_owner}/{repo_name}",
            "action": "play",
            "ascii_art": ascii_art,
            "pet": {
                "name": pet.name,
                "mood": pet.mood,
                "weight": weight_label(pet.weight),
            },
            "cheered_up": mood_changed,
        }
        if on_cooldown:
            response["note"] = (
                f"{pet.name} already got some attention recently — "
                "check back later for another mood boost."
            )
        if message:
            response["message"] = message
        return response


@mcp.tool()
async def list_pets() -> dict[str, Any]:
    """List your own registered pets.

    Returns:
        Your pets and their current status
    """
    user_id = _current_user_id()
    async with async_session_factory() as session:
        result = await session.execute(select(Pet).where(Pet.user_id == user_id))
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
                    "weight": weight_label(pet.weight),
                }
                for pet in pets
            ],
            "count": len(pets),
        }


@mcp.tool()
async def get_pet_history(repo_owner: str, repo_name: str) -> dict[str, Any]:
    """Get the evolution history and stats for one of your pets.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Pet history including creation date, evolution stage, and stats
    """
    async with async_session_factory() as session:
        pet = await _get_owned_pet(session, repo_owner, repo_name)

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
                "weight": weight_label(pet.weight),
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
    """Sync one of your pets with its repository's current real activity.

    This is the only way health, XP, and evolution actually move — polls
    GitHub and applies a real delta. Also burns off weight gained from
    feed_pet, since this represents real work happening on the repo.

    Args:
        repo_owner: Owner of the GitHub repository
        repo_name: Name of the GitHub repository

    Returns:
        Updated pet status with changes from repo health check
    """
    async with async_session_factory() as session:
        pet = await _get_owned_pet(session, repo_owner, repo_name)

        github = GitHubService()
        health = await github.get_repo_health(repo_owner, repo_name)

        old_stage = pet.stage
        old_mood = pet.mood

        health_delta = calculate_health_delta(health)
        pet.health = max(0, min(100, pet.health + health_delta))

        exp_gained = calculate_experience(health)
        pet.experience += exp_gained

        weight_lost = apply_exercise_decay(pet)

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
                "weight": weight_label(pet.weight),
            },
            "changes": {
                "health_delta": health_delta,
                "experience_gained": exp_gained,
                "weight_lost": weight_lost,
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


@mcp.tool()
async def get_leaderboard(limit: int = 10) -> dict[str, Any]:
    """See the top pets on the public leaderboard, for comparing with your own.

    Same aggregate data (name, stage, health, rank) already public on the
    website leaderboard — no per-user detail beyond that, and pets whose
    owner opted out are excluded.

    Args:
        limit: Number of top pets to return (max 50)

    Returns:
        Ranked list of top pets by experience
    """
    limit = max(1, min(50, limit))
    async with async_session_factory() as session:
        result = await session.execute(
            select(Pet)
            .where(
                Pet.is_dead.is_(False),
                Pet.is_placeholder.is_(False),
                Pet.leaderboard_opt_out.is_(False),
            )
            .order_by(Pet.experience.desc())
            .limit(limit)
        )
        pets = result.scalars().all()

        return {
            "leaderboard": [
                {
                    "rank": i + 1,
                    "repo": f"{pet.repo_owner}/{pet.repo_name}",
                    "name": pet.name,
                    "stage": pet.stage,
                    "health": pet.health,
                    "experience": pet.experience,
                }
                for i, pet in enumerate(pets)
            ],
        }


def _try_storage() -> Any:
    """Best-effort StorageService — None if not configured, never raises."""
    try:
        if not _api_routes.settings.minio_endpoint:
            return None
        return _api_routes.StorageService()
    except Exception:
        return None


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
