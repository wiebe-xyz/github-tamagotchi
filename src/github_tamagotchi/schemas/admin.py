"""Admin request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PetAdminSettingsUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=20)
    blame_board_enabled: bool | None = None
    contributor_badges_enabled: bool | None = None
    leaderboard_opt_out: bool | None = None
    hungry_after_days: int | None = Field(None, ge=1, le=30)
    pr_review_sla_hours: int | None = Field(None, ge=1, le=336)
    issue_response_sla_days: int | None = Field(None, ge=1, le=90)


class ExcludedContributorItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    github_login: str
    excluded_by: str
    excluded_at: datetime


class PetAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    blame_board_enabled: bool
    contributor_badges_enabled: bool
    leaderboard_opt_out: bool
    hungry_after_days: int
    pr_review_sla_hours: int
    issue_response_sla_days: int
    excluded_contributors: list[ExcludedContributorItem]
    is_dead: bool
    generation: int
