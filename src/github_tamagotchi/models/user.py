"""User model for GitHub OAuth authenticated users."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from github_tamagotchi.models.pet import Base


class User(Base):
    """A user authenticated via GitHub OAuth."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    github_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    github_login: Mapped[str] = mapped_column(String(255), nullable=False)
    github_avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Encrypted GitHub access token
    encrypted_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
