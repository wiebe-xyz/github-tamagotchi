"""Alert model for tracking alert state and history."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from github_tamagotchi.models.pet import Base


class AlertSeverity(StrEnum):
    """Alert severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"


class AlertStatus(StrEnum):
    """Alert lifecycle states."""

    FIRING = "firing"
    RESOLVED = "resolved"


class AlertType(StrEnum):
    """Types of alerts the system can raise."""

    POLL_FAILED = "poll_failed"
    GITHUB_RATE_LIMITED = "github_rate_limited"
    HIGH_ERROR_RATE = "high_error_rate"
    DATABASE_SLOW = "database_slow"
    MANY_DYING_PETS = "many_dying_pets"
    PET_DEATH_SPIKE = "pet_death_spike"


ALERT_SEVERITY: dict[AlertType, AlertSeverity] = {
    AlertType.POLL_FAILED: AlertSeverity.CRITICAL,
    AlertType.GITHUB_RATE_LIMITED: AlertSeverity.WARNING,
    AlertType.HIGH_ERROR_RATE: AlertSeverity.WARNING,
    AlertType.DATABASE_SLOW: AlertSeverity.WARNING,
    AlertType.MANY_DYING_PETS: AlertSeverity.WARNING,
    AlertType.PET_DEATH_SPIKE: AlertSeverity.WARNING,
}


class Alert(Base):
    """Tracks alert state to avoid duplicate notifications."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AlertStatus.FIRING.value
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
