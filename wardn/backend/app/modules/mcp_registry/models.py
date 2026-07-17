import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.domain_types import (
    MCPCatalogSourceProvider,
    MCPCatalogSyncMode,
    MCPInstallationStatus,
    MCPOperationCleanupStatus,
    MCPOperationJobStatus,
    MCPServerStatus,
)
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MCPRepositoryMetadataRateLimit(Base):
    __tablename__ = "mcp_repository_metadata_rate_limits"
    __table_args__ = (
        CheckConstraint(
            "request_count > 0",
            name="ck_mcp_repository_metadata_rate_limits_request_count_positive",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    request_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="1",
    )


class MCPServerVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_server_versions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            "version",
            name="uq_mcp_server_versions_org_name_version",
        ),
        CheckConstraint(
            "status IN ('active', 'deprecated', 'deleted')",
            name="ck_mcp_server_versions_status",
        ),
        Index(
            "ix_mcp_server_versions_org_latest_page",
            "organization_id",
            "is_latest",
            "name",
            "version",
            "id",
            postgresql_where=text("status <> 'deleted'"),
        ),
        Index(
            "ix_mcp_server_versions_org_page",
            "organization_id",
            "name",
            "version",
            "id",
        ),
        Index(
            "ix_mcp_server_versions_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_mcp_server_versions_catalog_source",
            "organization_id",
            "catalog_source_id",
            postgresql_where=text("catalog_source_id IS NOT NULL"),
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "mcp_catalog_sources.id",
            name="fk_mcp_server_versions_catalog_source",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, "
            "coalesce(name, '') || ' ' || coalesce(title, '') || ' ' || "
            "coalesce(description, ''))",
            persisted=True,
        ),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(255), nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    status: Mapped[MCPServerStatus] = mapped_column(
        String(32),
        default=MCPServerStatus.ACTIVE,
        nullable=False,
        index=True,
    )
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
        CheckConstraint(
            "provider IN ('wardn_hub', 'official', 'pulsemcp', 'custom')",
            name="ck_mcp_catalog_sources_provider",
        ),
        CheckConstraint(
            "sync_mode IN ('latest_only', 'all_versions')",
            name="ck_mcp_catalog_sources_sync_mode",
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
    provider: Mapped[MCPCatalogSourceProvider] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sync_mode: Mapped[MCPCatalogSyncMode] = mapped_column(
        String(50),
        default=MCPCatalogSyncMode.LATEST_ONLY,
        nullable=False,
    )
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
        CheckConstraint(
            "status IN ('enabled', 'disabled')",
            name="ck_mcp_server_installations_status",
        ),
        Index(
            "ix_mcp_server_installations_enabled_page",
            "server_name",
            "id",
            postgresql_where=text("status = 'enabled'"),
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
    status: Mapped[MCPInstallationStatus] = mapped_column(
        String(32),
        default=MCPInstallationStatus.ENABLED,
        nullable=False,
        index=True,
    )
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
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_mcp_operation_jobs_status",
        ),
        CheckConstraint(
            "cleanup_status IN ('not_required', 'pending', 'running', 'succeeded', 'failed')",
            name="ck_mcp_operation_jobs_cleanup_status",
        ),
        CheckConstraint(
            "progress_current >= 0 AND progress_total >= 1 "
            "AND progress_current <= progress_total",
            name="ck_mcp_operation_jobs_progress",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 "
            "AND cleanup_attempt_count >= 0 AND cleanup_max_attempts >= 1",
            name="ck_mcp_operation_jobs_attempts",
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
    status: Mapped[MCPOperationJobStatus] = mapped_column(
        String(32),
        default=MCPOperationJobStatus.QUEUED,
        nullable=False,
        index=True,
    )
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
    cleanup_status: Mapped[MCPOperationCleanupStatus] = mapped_column(
        String(32),
        default=MCPOperationCleanupStatus.NOT_REQUIRED,
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
        Index(
            "ix_mcp_server_tool_schemas_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_mcp_server_tool_schemas_active_page",
            "server_name",
            "tool_name",
            "id",
            postgresql_where=text("is_active IS TRUE"),
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
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, "
            "coalesce(server_name, '') || ' ' || coalesce(tool_name, '') || ' ' || "
            "coalesce(title, '') || ' ' || coalesce(description, ''))",
            persisted=True,
        ),
        nullable=False,
    )
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
