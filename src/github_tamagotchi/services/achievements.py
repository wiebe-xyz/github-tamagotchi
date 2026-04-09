"""Achievement checking and unlocking logic."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from github_tamagotchi.models.achievement import PetAchievement
from github_tamagotchi.models.comment import PetComment
from github_tamagotchi.models.pet import Pet, PetStage

ACHIEVEMENTS: dict[str, dict[str, str]] = {
    "first_commit": {
        "name": "First Blood",
        "icon": "\U0001fa78",
        "description": "Made their first commit",
    },
    "week_warrior": {
        "name": "Week Warrior",
        "icon": "\U0001f525",
        "description": "Maintained a 7-day commit streak",
    },
    "month_legend": {
        "name": "Month Legend",
        "icon": "\U0001f3c6",
        "description": "Achieved a 30-day commit streak",
    },
    "hatchling": {
        "name": "Hatchling",
        "icon": "\U0001f423",
        "description": "Evolved to Baby stage",
    },
    "all_grown_up": {
        "name": "All Grown Up",
        "icon": "\U0001f989",
        "description": "Evolved to Adult stage",
    },
    "elder_god": {
        "name": "Elder God",
        "icon": "\U0001f985",
        "description": "Evolved to Elder stage",
    },
    "survivor": {
        "name": "Against All Odds",
        "icon": "\U0001f4aa",
        "description": "Recovered from critical health",
    },
    "centurion": {
        "name": "Centurion",
        "icon": "\U0001f4af",
        "description": "Maintained perfect health",
    },
    "social_butterfly": {
        "name": "Social Butterfly",
        "icon": "\u2b50",
        "description": "Received 10 or more comments",
    },
    "phoenix": {
        "name": "Phoenix",
        "icon": "\U0001f525",
        "description": "Rose from the ashes (resurrected)",
    },
}

# Achievement IDs in a defined order for display
ACHIEVEMENT_ORDER = [
    "first_commit",
    "week_warrior",
    "month_legend",
    "hatchling",
    "all_grown_up",
    "elder_god",
    "survivor",
    "centurion",
    "social_butterfly",
    "phoenix",
]


def _check_conditions(pet: Pet, comment_count: int) -> set[str]:
    """Return the set of achievement IDs that the pet currently qualifies for."""
    earned: set[str] = set()

    if pet.commit_streak >= 1 or pet.longest_streak >= 1 or pet.experience > 0:
        earned.add("first_commit")

    if pet.commit_streak >= 7:
        earned.add("week_warrior")

    if pet.longest_streak >= 30:
        earned.add("month_legend")

    stage = PetStage(pet.stage)
    stage_order = list(PetStage)
    current_idx = stage_order.index(stage)

    if current_idx >= stage_order.index(PetStage.BABY):
        earned.add("hatchling")

    if current_idx >= stage_order.index(PetStage.ADULT):
        earned.add("all_grown_up")

    if current_idx >= stage_order.index(PetStage.ELDER):
        earned.add("elder_god")

    # Survivor: pet has recovered — health is good but has seen some activity
    # Heuristic: health >= 50, experience > 0, not egg, and not dead
    if pet.health >= 50 and pet.experience > 0 and stage != PetStage.EGG and not pet.is_dead:
        earned.add("survivor")

    if pet.health == 100:
        earned.add("centurion")

    if comment_count >= 10:
        earned.add("social_butterfly")

    if pet.generation >= 2:
        earned.add("phoenix")

    return earned


async def check_and_unlock_achievements(pet: Pet, session: AsyncSession) -> list[str]:
    """Check all conditions and unlock any newly earned achievements.

    Returns list of newly unlocked achievement IDs.
    """
    # Fetch already-unlocked achievement IDs for this pet
    existing_result = await session.execute(
        select(PetAchievement.achievement_id).where(PetAchievement.pet_id == pet.id)
    )
    already_unlocked: set[str] = set(existing_result.scalars().all())

    # Count comments for social_butterfly
    comment_count_result = await session.execute(
        select(func.count()).select_from(PetComment).where(
            PetComment.repo_owner == pet.repo_owner,
            PetComment.repo_name == pet.repo_name,
        )
    )
    comment_count = comment_count_result.scalar() or 0

    earned = _check_conditions(pet, comment_count)
    newly_unlocked: list[str] = []

    for achievement_id in earned:
        if achievement_id in already_unlocked:
            continue
        new_achievement = PetAchievement(pet_id=pet.id, achievement_id=achievement_id)
        session.add(new_achievement)
        try:
            await session.flush()
            newly_unlocked.append(achievement_id)
        except IntegrityError:
            # Race condition: already inserted by concurrent request
            await session.rollback()

    return newly_unlocked


async def get_pet_achievements(
    pet_id: int, session: AsyncSession
) -> dict[str, "PetAchievement | None"]:
    """Return a mapping of achievement_id -> PetAchievement (or None if not unlocked)."""
    result = await session.execute(
        select(PetAchievement).where(PetAchievement.pet_id == pet_id)
    )
    unlocked_rows = {row.achievement_id: row for row in result.scalars().all()}
    return {aid: unlocked_rows.get(aid) for aid in ACHIEVEMENT_ORDER}
