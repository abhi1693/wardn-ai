import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentScope = Literal["organization", "workspace"]


class AgentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    instructions: str = Field(min_length=1, max_length=50000)
    scope: AgentScope = "organization"
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    provider_credential_id: uuid.UUID | None = Field(
        default=None,
        alias="providerCredentialId",
    )
    model_name: str = Field(default="", alias="modelName", max_length=255)

    @model_validator(mode="after")
    def validate_scope(self) -> "AgentCreate":
        if self.scope == "workspace" and self.workspace_id is None:
            raise ValueError("workspaceId is required for workspace-scoped agents")
        if self.scope != "workspace" and self.workspace_id is not None:
            raise ValueError("workspaceId is only valid for workspace-scoped agents")
        return self


class AgentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    instructions: str | None = Field(default=None, min_length=1, max_length=50000)
    scope: AgentScope | None = None
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    provider_credential_id: uuid.UUID | None = Field(
        default=None,
        alias="providerCredentialId",
    )
    model_name: str | None = Field(default=None, alias="modelName", max_length=255)
    is_active: bool | None = Field(default=None, alias="isActive")


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    organization_id: uuid.UUID = Field(alias="organizationId")
    workspace_id: uuid.UUID | None = Field(default=None, alias="workspaceId")
    created_by_id: uuid.UUID | None = Field(default=None, alias="createdById")
    provider_credential_id: uuid.UUID | None = Field(
        default=None,
        alias="providerCredentialId",
    )
    name: str
    description: str
    instructions: str
    scope: AgentScope
    model_name: str = Field(alias="modelName")
    is_active: bool = Field(alias="isActive")
    tool_count: int = Field(alias="toolCount")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class AgentListResponse(BaseModel):
    agents: list[AgentRead]


class AgentToolAssignmentUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tool_schema_ids: list[uuid.UUID] = Field(default_factory=list, alias="toolSchemaIds")


class AgentToolRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    agent_id: uuid.UUID = Field(alias="agentId")
    tool_schema_id: uuid.UUID = Field(alias="toolSchemaId")
    installation_id: uuid.UUID = Field(alias="installationId")
    workspace_id: uuid.UUID = Field(alias="workspaceId")
    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    tool_name: str = Field(alias="toolName")
    title: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(alias="createdAt")


class AgentToolListResponse(BaseModel):
    tools: list[AgentToolRead]


class AgentAvailableToolRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tool_schema_id: uuid.UUID = Field(alias="toolSchemaId")
    installation_id: uuid.UUID = Field(alias="installationId")
    workspace_id: uuid.UUID = Field(alias="workspaceId")
    server_name: str = Field(alias="serverName")
    config_name: str = Field(alias="configName")
    tool_name: str = Field(alias="toolName")
    title: str
    description: str
    input_schema: dict[str, Any] = Field(alias="inputSchema")
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: dict[str, Any] = Field(default_factory=dict)


class AgentAvailableToolListResponse(BaseModel):
    tools: list[AgentAvailableToolRead]


class AgentChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    parts: list[dict[str, Any]] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    messages: list[AgentChatMessage] = Field(default_factory=list)
