"""Pet information request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
