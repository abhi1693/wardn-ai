import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MCPServerVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_versions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            "version",
            name="uq_mcp_server_versions_org_name_version",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    status_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    repository: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    packages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    remotes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    icons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    server_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class MCPCatalogSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_catalog_sources"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_mcp_catalog_sources_org_name",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sync_mode: Mapped[str] = mapped_column(String(50), default="latest_only", nullable=False)
    secret_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_updated_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class MCPServerInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_installations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "server_name",
            "config_name",
            name="uq_mcp_server_installations_workspace_server_config",
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    server_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    config_name: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    installed_version: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="enabled", nullable=False, index=True)
    install_type: Mapped[str] = mapped_column(String(32), default="metadata", nullable=False)
    install_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    runtime_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    secret_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    install_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class MCPServerToolSchema(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_tool_schemas"
    __table_args__ = (
        UniqueConstraint(
            "server_name",
            "server_version",
            "tool_name",
            name="uq_mcp_server_tool_schemas_server_version_tool",
        ),
    )

    server_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    server_version: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
