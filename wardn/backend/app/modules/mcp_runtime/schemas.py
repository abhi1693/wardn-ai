from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.core.schemas import APIModel


class MCPRuntimeSessionRead(APIModel):
    id: UUID
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    installation_id: UUID
    server_name: str
    server_version: str
    runtime_provider: str
    runtime_kind: str
    status: str
    pod_name: str
    namespace: str
    started_at: datetime | None = None
    ready_at: datetime | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    stopped_at: datetime | None = None
    failure_count: int
    last_error: str


class MCPRuntimeSessionListResponse(APIModel):
    sessions: list[MCPRuntimeSessionRead]


class MCPRuntimeSessionHealthResponse(APIModel):
    runtime_session_id: UUID
    runtime_provider: str
    runtime_kind: str
    status: str
    healthy: bool
    ready: bool
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MCPRuntimeEventRead(APIModel):
    id: UUID
    runtime_session_id: UUID
    event_type: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MCPRuntimeEventListResponse(APIModel):
    events: list[MCPRuntimeEventRead]


class MCPRuntimeToolCallSummary(APIModel):
    total: int
    succeeded: int
    failed: int
    running: int
    recent_total: int
    recent_failed: int
    recent_failure_rate: float


class MCPRuntimeServerError(APIModel):
    server_name: str
    server_version: str
    last_error: str
    last_error_at: datetime | None = None
    failure_count: int


class MCPRuntimeSummaryResponse(APIModel):
    total_sessions: int
    active_sessions: int
    idle_sessions: int
    failed_sessions: int
    stopped_sessions: int
    expired_sessions: int
    stale_active_sessions: int
    session_status_counts: dict[str, int]
    tool_calls: MCPRuntimeToolCallSummary
    recent_server_errors: list[MCPRuntimeServerError]
