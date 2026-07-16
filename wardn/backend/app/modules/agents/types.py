import uuid
from dataclasses import dataclass
from typing import Any

from app.modules.guardrails.service import GuardrailDecision
from app.modules.mcp_registry.models import (
    MCPServerInstallation,
    MCPServerToolSchema,
    MCPServerVersion,
)


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
class AgentRuntimeToolGuardrailFilter:
    allowed_tools: dict[str, AgentRuntimeTool]
    denied_tools: dict[str, tuple[AgentRuntimeTool, GuardrailDecision]]


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
    result: str | None = None
    approval: dict[str, Any] | None = None


@dataclass(frozen=True)
class AgentChatTextEvent:
    text: str


@dataclass(frozen=True)
class AgentChatToolActivityEvent:
    id: str
    tool_name: str
    status: str
    arguments: dict[str, Any] | None = None
    error: str | None = None
    message: str | None = None
    progress: float | int | None = None
    progress_token: str | int | None = None
    result: str | None = None
    total: float | int | None = None
    approval: dict[str, Any] | None = None


AgentChatStreamEvent = AgentChatTextEvent | AgentChatToolActivityEvent
