"""Social request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LeaderboardEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    pet_name: str
    repo_owner: str
    repo_name: str
    stage: str
    value: int


class LeaderboardCategory(BaseModel):
    id: str
    title: str
    description: str
    entries: list[LeaderboardEntry]


class LeaderboardResponse(BaseModel):
    categories: list[LeaderboardCategory]
    cached_at: datetime
