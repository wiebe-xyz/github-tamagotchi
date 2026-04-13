"""Pet request/response schemas."""

from pydantic import BaseModel, ConfigDict, Field

from github_tamagotchi.services.image_generation import DEFAULT_STYLE


class PetCreate(BaseModel):
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
    died_at: object | None
    cause_of_death: str | None
    personality_activity: float | None
    personality_sociability: float | None
    personality_bravery: float | None
    personality_tidiness: float | None
    personality_appetite: float | None
    created_at: object
    updated_at: object
    last_fed_at: object | None
    last_checked_at: object | None
    dependent_count: int
    grace_period_started: object | None


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
    style: str = Field(..., min_length=1, max_length=30)


class PetRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)


class BadgeStyleUpdateRequest(BaseModel):
    badge_style: str = Field(..., min_length=1, max_length=20)


class SkinInfo(BaseModel):
    skin: str
    unlocked: bool
    unlock_condition: str


class SkinSelectRequest(BaseModel):
    skin: str = Field(..., min_length=1, max_length=20)


class SkinSelectResponse(BaseModel):
    message: str
    pet: PetResponse


class ImageGenerationResponse(BaseModel):
    message: str
    stages: list[str]
