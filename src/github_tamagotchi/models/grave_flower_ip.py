"""Rate-limiting model for grave flower reactions."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from github_tamagotchi.models.pet import Base


class GraveFlowerIp(Base):
    """Tracks per-IP rate limits for flower reactions on graves."""

    __tablename__ = "grave_flower_ips"
    __table_args__ = (UniqueConstraint("pet_id", "ip_hash", name="uq_grave_flower_ip"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_flower_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
