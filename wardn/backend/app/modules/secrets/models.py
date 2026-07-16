import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SecretStore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "secret_stores"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "name",
            name="uq_secret_stores_org_workspace_name",
        ),
        Index(
            "uq_secret_stores_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=text("workspace_id is null"),
        ),
        Index(
            "uq_secret_stores_org_provider_base_url",
            "organization_id",
            "provider",
            text(
                "lower(regexp_replace("
                "btrim(coalesce(config ->> 'baseUrl', config ->> 'base_url')), "
                "'/+$', ''"
                "))"
            ),
            unique=True,
            postgresql_where=text(
                "provider = 'openbao' "
                "and coalesce(config ->> 'baseUrl', config ->> 'base_url', '') <> ''"
            ),
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    auth_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class ManagedSecret(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable ownership and cleanup state for a Wardn-written external secret path."""

    __tablename__ = "managed_secrets"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "external_ref",
            name="uq_managed_secrets_store_external_ref",
        ),
        CheckConstraint(
            "status IN ('provisioning', 'active', 'cleanup_pending', 'cleaning', "
            "'cleanup_failed')",
            name="ck_managed_secrets_status",
        ),
        CheckConstraint(
            "cleanup_attempt_count >= 0 AND cleanup_max_attempts >= 1",
            name="ck_managed_secrets_cleanup_attempts",
        ),
        Index(
            "ix_managed_secrets_cleanup_claimable",
            "status",
            "cleanup_available_at",
            "created_at",
        ),
        Index(
            "ix_managed_secrets_owner",
            "owner_type",
            "owner_id",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "organizations.id",
            name="fk_managed_secrets_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "workspaces.id",
            name="fk_managed_secrets_workspace",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "secret_stores.id",
            name="fk_managed_secrets_store",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_type: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="provisioning",
        nullable=False,
        index=True,
    )
    cleanup_available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    cleanup_attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cleanup_max_attempts: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    cleanup_worker_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    cleanup_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    cleanup_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SecretHandle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "secret_handles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "workspace_id",
            "display_name",
            name="uq_secret_handles_org_workspace_display_name",
        ),
        Index(
            "uq_secret_handles_org_display_name",
            "organization_id",
            "display_name",
            unique=True,
            postgresql_where=text("workspace_id is null"),
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
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("secret_stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    managed_secret_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "managed_secrets.id",
            name="fk_secret_handles_managed_secret",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    key_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    version: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    handle_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
