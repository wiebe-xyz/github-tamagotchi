"""PetAchievement model for tracking unlocked achievements per pet."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from github_tamagotchi.models.pet import Base


class PetAchievement(Base):
    """An achievement unlocked by a pet."""

    __tablename__ = "pet_achievements"
    __table_args__ = (UniqueConstraint("pet_id", "achievement_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    achievement_id: Mapped[str] = mapped_column(String(50), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
