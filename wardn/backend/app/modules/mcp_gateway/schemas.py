import uuid
from datetime import datetime
from typing import Any, Literal

from app.core.schemas import APIModel


class MCPGatewayToolApprovalRead(APIModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    workspace_id: uuid.UUID
    requested_by_id: uuid.UUID | None = None
    decided_by_id: uuid.UUID | None = None
    installation_id: uuid.UUID
    tool_schema_id: uuid.UUID | None = None
    tool_call_id: str
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    request_meta: dict[str, Any]
    guardrail: dict[str, Any]
    status: str
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: datetime
    updated_at: datetime


class MCPGatewayToolApprovalListResponse(APIModel):
    approvals: list[MCPGatewayToolApprovalRead]


class MCPGatewayToolApprovalDecisionRequest(APIModel):
    decision: Literal["approve", "deny"]


class MCPGatewayToolApprovalDecisionResponse(APIModel):
    approval_id: uuid.UUID
    status: str
    tool_name: str
    result: dict[str, Any] | None = None
    error: str = ""
