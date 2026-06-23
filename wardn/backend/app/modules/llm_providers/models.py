import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class LLMProviderCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_llm_provider_credentials_org_name",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    auth_method: Mapped[str] = mapped_column(
        String(32),
        default="api_key",
        nullable=False,
        index=True,
    )
    secret_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    oauth_provider: Mapped[str] = mapped_column(String(50), default="", nullable=False, index=True)
    oauth_access_token: Mapped[str] = mapped_column(Text, default="", nullable=False)
    oauth_refresh_token: Mapped[str] = mapped_column(Text, default="", nullable=False)
    oauth_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    oauth_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    oauth_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    extra_headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
