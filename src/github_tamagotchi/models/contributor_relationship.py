"""ContributorRelationship model for tracking per-contributor pet standing."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from github_tamagotchi.models.pet import Base


class ContributorStanding:
    """Standing values for contributor relationships."""

    FAVORITE = "favorite"
    GOOD = "good"
    NEUTRAL = "neutral"
    DOGHOUSE = "doghouse"
    ABSENT = "absent"


class ContributorRelationship(Base):
    """A pet's relationship with a contributor (github user)."""

    __tablename__ = "contributor_relationships"
    __table_args__ = (UniqueConstraint("pet_id", "github_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_username: Mapped[str] = mapped_column(String(255), nullable=False)
    standing: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ContributorStanding.NEUTRAL
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sins: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    good_deeds: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
