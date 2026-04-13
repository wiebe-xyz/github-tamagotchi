"""Pet request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from github_tamagotchi.services.image_generation import DEFAULT_STYLE


class PetCreate(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    repo_owner: str = Field(..., min_length=1, max_length=255)
    repo_name: str = Field(..., min_length=1, max_length=255)
    name: str | None = Field(None, min_length=1, max_length=20)
    style: str = Field(DEFAULT_STYLE, min_length=1, max_length=30)


class PetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_owner: str
    repo_name: str
    name: str
    stage: str
    mood: str
    health: int
    experience: int
    skin: str
    low_health_recoveries: int
    style: str
    badge_style: str
    commit_streak: int
    longest_streak: int
    generation: int
    is_dead: bool
    died_at: datetime | None
    cause_of_death: str | None
    personality_activity: float | None = Field(None, ge=0.0, le=1.0)
    personality_sociability: float | None = Field(None, ge=0.0, le=1.0)
    personality_bravery: float | None = Field(None, ge=0.0, le=1.0)
    personality_tidiness: float | None = Field(None, ge=0.0, le=1.0)
    personality_appetite: float | None = Field(None, ge=0.0, le=1.0)
    created_at: datetime
    updated_at: datetime
    last_fed_at: datetime | None
    last_checked_at: datetime | None
    dependent_count: int
    grace_period_started: datetime | None


class PetListResponse(BaseModel):
    items: list[PetResponse]
    total: int
    page: int
    per_page: int
    pages: int


class FeedResponse(BaseModel):
    message: str
    pet: PetResponse


class RepoItem(BaseModel):
    full_name: str
    owner: str
    name: str
    description: str | None
    private: bool
    has_pet: bool
    pet_name: str | None


class StyleUpdateRequest(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    style: str = Field(..., min_length=1, max_length=30)


class PetRenameRequest(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    name: str = Field(..., min_length=1, max_length=20)


class BadgeStyleUpdateRequest(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    badge_style: str = Field(..., min_length=1, max_length=20)


class SkinInfo(BaseModel):
    skin: str
    unlocked: bool
    unlock_condition: str


class SkinSelectRequest(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    skin: str = Field(..., min_length=1, max_length=20)


class SkinSelectResponse(BaseModel):
    message: str
    pet: PetResponse


class ImageGenerationResponse(BaseModel):
    message: str
    stages: list[str]
