import uuid
from dataclasses import dataclass
from typing import Any

from app.modules.guardrails.service import GuardrailDecision
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)

FAILURE_TOOL_NOT_INSTALLED = "tool_not_installed"
FAILURE_TOOL_INSTALLED_NOT_ASSIGNED = "tool_installed_not_assigned"
FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY = "tool_assigned_blocked_policy"
FAILURE_TOOL_SELECTED_RUNTIME_FAILED = "tool_selected_runtime_failed"
FAILURE_TOOL_RAN_UPSTREAM_REJECTED = "tool_ran_upstream_rejected"
FAILURE_TARGET_MISMATCH_BLOCKED = "target_mismatch_blocked"


class AgentChatProviderError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AgentRuntimeTool:
    wire_name: str
    assignment_id: uuid.UUID
    tool_schema: MCPServerToolSchema
    installation: MCPServerInstallation
    server: MCPServerVersion


@dataclass(frozen=True)
class AgentInstalledTool:
    tool_schema: MCPServerToolSchema
    installation: MCPServerInstallation


@dataclass(frozen=True)
class AgentRuntimeToolGuardrailFilter:
    allowed_tools: dict[str, AgentRuntimeTool]
    denied_tools: dict[str, tuple[AgentRuntimeTool, GuardrailDecision]]
    installed_tools: dict[str, AgentInstalledTool] | None = None


@dataclass(frozen=True)
class AgentToolCall:
    name: str
    call_id: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class AgentToolExecutionResult:
    output: str
    status: str
    error: str | None = None
    failure_reason: str | None = None
    result: str | None = None
    details: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentChatTextEvent:
    text: str


@dataclass(frozen=True)
class AgentChatReasoningSummaryEvent:
    summary: str


@dataclass(frozen=True)
class AgentChatToolActivityEvent:
    id: str
    tool_name: str
    status: str
    arguments: dict[str, Any] | None = None
    error: str | None = None
    failure_reason: str | None = None
    message: str | None = None
    progress: float | int | None = None
    progress_token: str | int | None = None
    result: str | None = None
    details: dict[str, Any] | None = None
    total: float | int | None = None
    approval: dict[str, Any] | None = None


AgentChatStreamEvent = (
    AgentChatTextEvent | AgentChatReasoningSummaryEvent | AgentChatToolActivityEvent
)
