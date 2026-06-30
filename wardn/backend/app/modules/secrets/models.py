import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
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
