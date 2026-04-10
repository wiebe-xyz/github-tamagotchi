"""Pet model representing a GitHub repository's health."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from github_tamagotchi.models.excluded_contributor import ExcludedContributor
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


class PetSkin(StrEnum):
    """Visual skin applied to the pet's badge."""

    CLASSIC = "classic"
    ROBOT = "robot"
    DRAGON = "dragon"
    GHOST = "ghost"


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

    # Skin
    skin: Mapped[str] = mapped_column(String(20), default=PetSkin.CLASSIC.value)
    low_health_recoveries: Mapped[int] = mapped_column(Integer, default=0)

    # Personality traits (0.0 to 1.0), generated once at creation
    personality_activity: Mapped[float | None] = mapped_column(Float, nullable=True)  # lazy→active
    personality_sociability: Mapped[float | None] = mapped_column(  # shy→social
        Float, nullable=True
    )
    personality_bravery: Mapped[float | None] = mapped_column(  # cautious→brave
        Float, nullable=True
    )
    personality_tidiness: Mapped[float | None] = mapped_column(Float, nullable=True)  # messy→neat
    personality_appetite: Mapped[float | None] = mapped_column(Float, nullable=True)  # light→hungry

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

    # Popularity metrics (stars/forks) — cosmetic only, do not affect health
    star_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    fork_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Leaderboard visibility (opt-out)
    leaderboard_opt_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Blame board visibility (opt-out by repo admin)
    blame_board_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Contributor badges visibility (opt-out by repo admin)
    contributor_badges_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Admin-configurable thresholds
    hungry_after_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    pr_review_sla_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=48, server_default="48"
    )
    issue_response_sla_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7"
    )

    # Dependent count — repos/packages that depend on this one (responsibility indicator)
    dependent_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Canonical appearance description used for sprite sheet generation consistency
    canonical_appearance: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    image_jobs: Mapped[list["ImageGenerationJob"]] = relationship(
        "ImageGenerationJob", back_populates="pet", cascade="all, delete-orphan"
    )
    excluded_contributors: Mapped[list["ExcludedContributor"]] = relationship(
        "ExcludedContributor", back_populates="pet", cascade="all, delete-orphan"
    )
