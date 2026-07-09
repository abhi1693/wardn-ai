import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MCPRuntimeSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_runtime_sessions"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_server_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    server_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    server_version: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    runtime_provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    runtime_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    config_fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    pod_name: Mapped[str] = mapped_column(String(253), default="", nullable=False)
    namespace: Mapped[str] = mapped_column(String(253), default="", nullable=False)
    endpoint_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class MCPToolInvocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_tool_invocations"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    runtime_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_runtime_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    installation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_server_installations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    server_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    server_version: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class MCPRuntimeEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "mcp_runtime_events"

    runtime_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mcp_runtime_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
