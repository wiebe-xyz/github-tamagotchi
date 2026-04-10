"""PetMilestone model for tracking evolution events."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from github_tamagotchi.models.pet import Base


class PetMilestone(Base):
    """An evolution milestone reached by a pet."""

    __tablename__ = "pet_milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    old_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    new_stage: Mapped[str] = mapped_column(String(20), nullable=False)
    experience: Mapped[int] = mapped_column(Integer, nullable=False)
    age_days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
