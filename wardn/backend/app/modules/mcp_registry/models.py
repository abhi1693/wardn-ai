import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
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

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
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
        UniqueConstraint(
            "organization_id",
            "base_url",
            name="uq_mcp_catalog_sources_org_base_url",
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
    auth_secret_handle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("secret_handles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    secret_references: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    install_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class MCPOperationJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_operation_jobs"
    __table_args__ = (
        Index(
            "uq_mcp_operation_jobs_active_dedupe",
            "deduplication_key",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index(
            "ix_mcp_operation_jobs_claimable",
            "status",
            "available_at",
            "created_at",
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
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    operation: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    progress_current: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_total: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    progress_message: Mapped[str] = mapped_column(Text, default="Queued", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    worker_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cleanup_status: Mapped[str] = mapped_column(
        String(32),
        default="not_required",
        nullable=False,
        index=True,
    )
    cleanup_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    cleanup_attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cleanup_max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    cleanup_available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    cleanup_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    cleanup_worker_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    cleanup_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class MCPOperationJobEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mcp_operation_job_events"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_operation_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(20), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    progress_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
        index=True,
    )


class MCPServerToolSchema(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_tool_schemas"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "tool_name",
            name="uq_mcp_server_tool_schemas_installation_tool",
        ),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    installation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_server_installations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
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
