import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    last_name: Mapped[str] = mapped_column(String(150), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    local_credentials: Mapped["LocalAuthCredential | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    tokens: Mapped[list["UserAPIToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email


class LocalAuthCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "local_auth_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="local_credentials")


class UserAPIToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_api_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="tokens")
