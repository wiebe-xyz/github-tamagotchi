"""Model for contributors excluded from a pet's tracking."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from github_tamagotchi.models.pet import Base

if TYPE_CHECKING:
    from github_tamagotchi.models.pet import Pet


class ExcludedContributor(Base):
    """A GitHub user excluded from a pet's contributor tracking."""

    __tablename__ = "excluded_contributors"
    __table_args__ = (
        UniqueConstraint("pet_id", "github_login", name="ix_excluded_contributors_pet_login"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pet_id: Mapped[int] = mapped_column(Integer, ForeignKey("pets.id"), nullable=False, index=True)
    github_login: Mapped[str] = mapped_column(String(255), nullable=False)
    excluded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    excluded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    pet: Mapped[Pet] = relationship("Pet", back_populates="excluded_contributors")
