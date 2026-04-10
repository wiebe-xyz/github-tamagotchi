"""Pet model representing a GitHub repository's health."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from github_tamagotchi.models.image_job import ImageGenerationJob


class Base(DeclarativeBase):
    """Base class for all models."""


class PetStage(StrEnum):
    """Evolution stages of the pet."""

    EGG = "egg"
    BABY = "baby"
    CHILD = "child"
    TEEN = "teen"
    ADULT = "adult"
    ELDER = "elder"


class PetMood(StrEnum):
    """Current mood of the pet based on repo health."""

    HAPPY = "happy"
    CONTENT = "content"
    HUNGRY = "hungry"
    WORRIED = "worried"
    LONELY = "lonely"
    SICK = "sick"
    DANCING = "dancing"


class Pet(Base):
    """A virtual pet representing a GitHub repository."""

    __tablename__ = "pets"
    __table_args__ = (UniqueConstraint("repo_owner", "repo_name", name="ix_pets_repo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_name: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )

    # Pet state
    stage: Mapped[str] = mapped_column(String(20), default=PetStage.EGG.value)
    mood: Mapped[str] = mapped_column(String(20), default=PetMood.CONTENT.value)
    health: Mapped[int] = mapped_column(Integer, default=100)
    experience: Mapped[int] = mapped_column(Integer, default=0)
    style: Mapped[str] = mapped_column(
        String(30), nullable=False, default="kawaii", server_default="kawaii"
    )
    badge_style: Mapped[str] = mapped_column(
        String(20), nullable=False, default="playful", server_default="playful"
    )

    # Streak tracking
    commit_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    longest_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_streak_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_fed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    images_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Death state
    is_dead: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    died_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cause_of_death: Mapped[str | None] = mapped_column(String(50), nullable=True)
    grace_period_started: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Resurrection / generation tracking
    generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # Last-known health metric snapshots
    last_release_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_contributor_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Leaderboard visibility (opt-out)
    leaderboard_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Relationships
    image_jobs: Mapped[list["ImageGenerationJob"]] = relationship(
        "ImageGenerationJob", back_populates="pet", cascade="all, delete-orphan"
    )
