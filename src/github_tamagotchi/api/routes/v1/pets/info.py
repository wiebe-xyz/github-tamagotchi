"""Pet information endpoints.

Covers: characteristics, comments, achievements, milestones, contributors, blame-board.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select as sa_select

from github_tamagotchi.api.auth import get_current_user, get_optional_user
from github_tamagotchi.api.dependencies import DbSession, get_pet_or_404
from github_tamagotchi.models.user import User
from github_tamagotchi.services.image_generation import get_pet_appearance

router: APIRouter = APIRouter(prefix="/api/v1", tags=["pets"])


class PetCharacteristics(BaseModel):
    color: str
    accent_color: str
    body_type: str
    feature: str


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_name: str
    body: str
    created_at: datetime


class CommentsListResponse(BaseModel):
    comments: list[CommentResponse]


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=500)


class AchievementItem(BaseModel):
    id: str
    name: str
    icon: str
    description: str
    unlocked: bool
    unlocked_at: datetime | None


class AchievementsResponse(BaseModel):
    achievements: list[AchievementItem]


class MilestoneItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    old_stage: str
    new_stage: str
    experience: int
    age_days: int
    created_at: datetime


class MilestonesResponse(BaseModel):
    milestones: list[MilestoneItem]


class ContributorRelationshipItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    github_username: str
    standing: str
    score: int
    last_activity: datetime | None
    good_deeds: list[str]
    sins: list[str]


class ContributorRelationshipsResponse(BaseModel):
    contributors: list[ContributorRelationshipItem]


class BlameEntryItem(BaseModel):
    issue: str
    culprit: str
    how_long: str


class HeroEntryItem(BaseModel):
    good_deed: str
    hero: str
    when: str


class BlameBoardResponse(BaseModel):
    is_healthy: bool
    blame_board_enabled: bool
    blame_entries: list[BlameEntryItem]
    hero_entries: list[HeroEntryItem]


@router.get("/pets/{repo_owner}/{repo_name}/characteristics", response_model=PetCharacteristics)
async def get_characteristics(repo_owner: str, repo_name: str) -> PetCharacteristics:
    """Get the deterministic appearance characteristics for a pet."""
    appearance = get_pet_appearance(repo_owner, repo_name)
    return PetCharacteristics(
        color=appearance.color,
        accent_color=appearance.accent_color,
        body_type=appearance.body_type,
        feature=appearance.feature,
    )


@router.get("/pets/{repo_owner}/{repo_name}/comments", response_model=CommentsListResponse)
async def list_comments(
    repo_owner: str,
    repo_name: str,
    session: DbSession,
    _user: Annotated[User | None, Depends(get_optional_user)] = None,
) -> CommentsListResponse:
    """Return the newest 50 comments for a pet profile."""
    from github_tamagotchi.models.comment import PetComment

    result = await session.execute(
        sa_select(PetComment)
        .where(PetComment.repo_owner == repo_owner, PetComment.repo_name == repo_name)
        .order_by(PetComment.created_at.desc())
        .limit(50)
    )
    comments = result.scalars().all()
    return CommentsListResponse(comments=[CommentResponse.model_validate(c) for c in comments])


@router.post(
    "/pets/{repo_owner}/{repo_name}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    repo_owner: str,
    repo_name: str,
    comment_data: CommentCreate,
    session: DbSession,
    user: Annotated[User, Depends(get_current_user)],
) -> CommentResponse:
    """Post a comment on a pet profile. Requires authentication."""
    from github_tamagotchi.models.comment import PetComment

    comment = PetComment(
        repo_owner=repo_owner,
        repo_name=repo_name,
        user_id=user.id,
        author_name=user.github_login,
        body=comment_data.body,
    )
    session.add(comment)
    await session.commit()
    await session.refresh(comment)
    return CommentResponse.model_validate(comment)


@router.get("/pets/{repo_owner}/{repo_name}/achievements", response_model=AchievementsResponse)
async def get_pet_achievements(
    repo_owner: str, repo_name: str, session: DbSession
) -> AchievementsResponse:
    """Get all achievements for a pet, with unlock status."""
    from github_tamagotchi.services.achievements import ACHIEVEMENT_ORDER, ACHIEVEMENTS
    from github_tamagotchi.services.achievements import (
        get_pet_achievements as _get_pet_achievements,
    )

    pet = await get_pet_or_404(repo_owner, repo_name, session)
    achievement_map = await _get_pet_achievements(pet.id, session)
    items = []
    for aid in ACHIEVEMENT_ORDER:
        row = achievement_map[aid]
        items.append(
            AchievementItem(
                id=aid,
                name=str(ACHIEVEMENTS[aid]["name"]),
                icon=str(ACHIEVEMENTS[aid]["icon"]),
                description=str(ACHIEVEMENTS[aid]["description"]),
                unlocked=row is not None,
                unlocked_at=row.unlocked_at if row is not None else None,
            )
        )
    return AchievementsResponse(achievements=items)


@router.get("/pets/{repo_owner}/{repo_name}/milestones", response_model=MilestonesResponse)
async def get_pet_milestones(
    repo_owner: str, repo_name: str, session: DbSession
) -> MilestonesResponse:
    """Get recent evolution milestones for a pet."""
    from github_tamagotchi.crud.milestone import get_milestones

    pet = await get_pet_or_404(repo_owner, repo_name, session)
    milestones = await get_milestones(session, pet.id)
    return MilestonesResponse(milestones=[MilestoneItem.model_validate(m) for m in milestones])


@router.get(
    "/pets/{repo_owner}/{repo_name}/contributors",
    response_model=ContributorRelationshipsResponse,
)
async def get_pet_contributors(
    repo_owner: str, repo_name: str, session: DbSession
) -> ContributorRelationshipsResponse:
    """Get contributor relationships for a pet."""
    from github_tamagotchi.crud.contributor_relationship import get_contributors_for_pet

    pet = await get_pet_or_404(repo_owner, repo_name, session)
    contributors = await get_contributors_for_pet(session, pet.id)
    return ContributorRelationshipsResponse(
        contributors=[ContributorRelationshipItem.model_validate(c) for c in contributors]
    )


@router.get("/pets/{repo_owner}/{repo_name}/blame-board", response_model=BlameBoardResponse)
async def get_blame_board(
    repo_owner: str, repo_name: str, session: DbSession
) -> BlameBoardResponse:
    """Get the blame/heroes board for a pet."""
    from github_tamagotchi.services.github import GitHubService

    pet = await get_pet_or_404(repo_owner, repo_name, session)

    if not pet.blame_board_enabled or pet.is_dead:
        return BlameBoardResponse(
            is_healthy=pet.health >= 50,
            blame_board_enabled=pet.blame_board_enabled,
            blame_entries=[],
            hero_entries=[],
        )

    gh = GitHubService()
    board = await gh.get_blame_board_data(repo_owner, repo_name, pet.health, pet.mood)

    return BlameBoardResponse(
        is_healthy=board.is_healthy,
        blame_board_enabled=True,
        blame_entries=[
            BlameEntryItem(issue=e.issue, culprit=e.culprit, how_long=e.how_long)
            for e in board.blame_entries
        ],
        hero_entries=[
            HeroEntryItem(good_deed=e.good_deed, hero=e.hero, when=e.when)
            for e in board.hero_entries
        ],
    )
