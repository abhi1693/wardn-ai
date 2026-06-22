from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MCPRuntimeSessionRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID | None = Field(default=None, alias="organizationId")
    workspace_id: UUID | None = Field(default=None, alias="workspaceId")
    installation_id: UUID = Field(alias="installationId")
    server_name: str = Field(alias="serverName")
    server_version: str = Field(alias="serverVersion")
    runtime_provider: str = Field(alias="runtimeProvider")
    runtime_kind: str = Field(alias="runtimeKind")
    status: str
    pod_name: str = Field(alias="podName")
    namespace: str
    started_at: datetime | None = Field(default=None, alias="startedAt")
    ready_at: datetime | None = Field(default=None, alias="readyAt")
    last_used_at: datetime | None = Field(default=None, alias="lastUsedAt")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    stopped_at: datetime | None = Field(default=None, alias="stoppedAt")
    failure_count: int = Field(alias="failureCount")
    last_error: str = Field(alias="lastError")


class MCPRuntimeSessionListResponse(BaseModel):
    sessions: list[MCPRuntimeSessionRead]


class MCPRuntimeEventRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    runtime_session_id: UUID = Field(alias="runtimeSessionId")
    event_type: str = Field(alias="eventType")
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")


class MCPRuntimeEventListResponse(BaseModel):
    events: list[MCPRuntimeEventRead]


class MCPRuntimeToolCallSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total: int
    succeeded: int
    failed: int
    running: int
    recent_total: int = Field(alias="recentTotal")
    recent_failed: int = Field(alias="recentFailed")
    recent_failure_rate: float = Field(alias="recentFailureRate")


class MCPRuntimeServerError(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    server_name: str = Field(alias="serverName")
    server_version: str = Field(alias="serverVersion")
    last_error: str = Field(alias="lastError")
    last_error_at: datetime | None = Field(default=None, alias="lastErrorAt")
    failure_count: int = Field(alias="failureCount")


class MCPRuntimeSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_sessions: int = Field(alias="totalSessions")
    active_sessions: int = Field(alias="activeSessions")
    idle_sessions: int = Field(alias="idleSessions")
    failed_sessions: int = Field(alias="failedSessions")
    stopped_sessions: int = Field(alias="stoppedSessions")
    expired_sessions: int = Field(alias="expiredSessions")
    stale_active_sessions: int = Field(alias="staleActiveSessions")
    session_status_counts: dict[str, int] = Field(alias="sessionStatusCounts")
    tool_calls: MCPRuntimeToolCallSummary = Field(alias="toolCalls")
    recent_server_errors: list[MCPRuntimeServerError] = Field(alias="recentServerErrors")
