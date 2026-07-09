from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MCPToolUsageRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    organization_id: UUID | None = Field(default=None, alias="organizationId")
    workspace_id: UUID | None = Field(default=None, alias="workspaceId")
    runtime_session_id: UUID | None = Field(default=None, alias="runtimeSessionId")
    installation_id: UUID = Field(alias="installationId")
    user_id: UUID | None = Field(default=None, alias="userId")
    user_email: str = Field(alias="userEmail")
    user_display_name: str = Field(alias="userDisplayName")
    agent_id: UUID | None = Field(default=None, alias="agentId")
    agent_name: str = Field(alias="agentName")
    agent_run_id: UUID | None = Field(default=None, alias="agentRunId")
    server_name: str = Field(alias="serverName")
    server_version: str = Field(alias="serverVersion")
    tool_name: str = Field(alias="toolName")
    status: str
    started_at: datetime = Field(alias="startedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    input_size_bytes: int = Field(alias="inputSizeBytes")
    output_size_bytes: int = Field(alias="outputSizeBytes")
    is_error: bool = Field(alias="isError")
    error: str


class MCPToolUsageSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total: int
    succeeded: int
    failed: int
    running: int
    attributed: int
    unattributed: int
    average_duration_ms: int | None = Field(default=None, alias="averageDurationMs")


class MCPToolUsageListResponse(BaseModel):
    summary: MCPToolUsageSummary
    tool_calls: list[MCPToolUsageRead] = Field(alias="toolCalls")
