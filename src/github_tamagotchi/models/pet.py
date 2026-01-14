"""Pet model representing a GitHub repository's health."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from github_tamagotchi.models.image_job import ImageGenerationJob


class Base(DeclarativeBase):
    """Base class for all models."""


class PetStage(str, Enum):
    """Evolution stages of the pet."""

    EGG = "egg"
    BABY = "baby"
    CHILD = "child"
    TEEN = "teen"
    ADULT = "adult"
    ELDER = "elder"


class PetMood(str, Enum):
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

    # Pet state
    stage: Mapped[str] = mapped_column(String(20), default=PetStage.EGG.value)
    mood: Mapped[str] = mapped_column(String(20), default=PetMood.CONTENT.value)
    health: Mapped[int] = mapped_column(Integer, default=100)
    experience: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_fed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    image_jobs: Mapped[list["ImageGenerationJob"]] = relationship(
        "ImageGenerationJob", back_populates="pet", cascade="all, delete-orphan"
    )
