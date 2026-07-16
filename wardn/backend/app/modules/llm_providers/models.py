import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.domain_types import LLMProviderAuthMethod, LLMProviderVisibility
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class LLMProviderCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "llm_provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_llm_provider_credentials_org_name",
        ),
        CheckConstraint(
            "visibility IN ('organization', 'workspace', 'user')",
            name="ck_llm_provider_credentials_visibility",
        ),
        CheckConstraint(
            "(visibility = 'organization' AND workspace_id IS NULL AND user_id IS NULL) OR "
            "(visibility = 'workspace' AND workspace_id IS NOT NULL AND user_id IS NULL) OR "
            "(visibility = 'user' AND workspace_id IS NULL AND user_id IS NOT NULL)",
            name="ck_llm_provider_credentials_visibility_scope",
        ),
        CheckConstraint(
            "auth_method IN ('api_key', 'oauth')",
            name="ck_llm_provider_credentials_auth_method",
        ),
        CheckConstraint(
            "(auth_method = 'api_key' AND api_key_secret_handle_id IS NOT NULL) OR "
            "(auth_method = 'oauth' AND oauth_provider = 'chatgpt' "
            "AND oauth_access_token_secret_handle_id IS NOT NULL "
            "AND oauth_refresh_token_secret_handle_id IS NOT NULL)",
            name="ck_llm_provider_credentials_auth_material",
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
    visibility: Mapped[LLMProviderVisibility] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    auth_method: Mapped[LLMProviderAuthMethod] = mapped_column(
        String(32),
        default=LLMProviderAuthMethod.API_KEY,
        nullable=False,
        index=True,
    )
    api_key_secret_handle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "secret_handles.id",
            name="fk_llm_provider_credentials_api_key_secret_handle",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    oauth_provider: Mapped[str] = mapped_column(String(50), default="", nullable=False, index=True)
    oauth_access_token_secret_handle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "secret_handles.id",
            name="fk_llm_provider_credentials_oauth_access_secret_handle",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    oauth_refresh_token_secret_handle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "secret_handles.id",
            name="fk_llm_provider_credentials_oauth_refresh_secret_handle",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    oauth_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    oauth_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    oauth_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    extra_headers: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
