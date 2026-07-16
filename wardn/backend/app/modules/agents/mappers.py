import re
import uuid
from typing import Any

from app.modules.agents.exceptions import InvalidAgentToolAssignmentError
from app.modules.agents.models import Agent, AgentRun, ConversationMessage, WorkspaceConversation
from app.modules.agents.schemas import (
    TOOL_ASSIGNMENT_WILDCARD,
    AgentRead,
    AgentRunRead,
    AgentRunStepRead,
    AgentServerToolAssignmentRead,
    AgentToolRead,
    ConversationMessageRead,
    WorkspaceConversationRead,
)

AGENT_RUN_PAYLOAD_STRING_MAX_CHARS = 4_000
SENSITIVE_TEXT_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|authorization|client[_-]?secret|password|refresh[_-]?token|secret|token)"
        r"\s*[:=]\s*['\"]?[^'\"\s,}]+"
    ),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def text_parts(content: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": content}]


def is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").casefold()
    return any(
        marker in normalized
        for marker in (
            "api_key",
            "apikey",
            "authorization",
            "bearer",
            "client_secret",
            "cookie",
            "password",
            "refresh_token",
            "secret",
            "token",
        )
    )


def sanitize_run_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if is_sensitive_key(str(key)) else sanitize_run_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_run_payload(item) for item in value]
    if isinstance(value, str):
        sanitized = value
        for pattern in SENSITIVE_TEXT_PATTERNS:
            sanitized = pattern.sub("[redacted]", sanitized)
        if len(sanitized) > AGENT_RUN_PAYLOAD_STRING_MAX_CHARS:
            return sanitized[:AGENT_RUN_PAYLOAD_STRING_MAX_CHARS] + "\n[truncated]"
        return sanitized
    return value


def agent_response(agent: Agent, *, server_count: int, tool_count: int) -> AgentRead:
    return AgentRead(
        id=agent.id,
        organizationId=agent.organization_id,
        workspaceId=agent.workspace_id,
        createdById=agent.created_by_id,
        providerCredentialId=agent.provider_credential_id,
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        scope=agent.scope,
        modelName=agent.model_name,
        isActive=agent.is_active,
        serverCount=server_count,
        toolCount=tool_count,
        createdAt=agent.created_at,
        updatedAt=agent.updated_at,
    )


def conversation_response(conversation: WorkspaceConversation) -> WorkspaceConversationRead:
    return WorkspaceConversationRead(
        id=conversation.id,
        organizationId=conversation.organization_id,
        workspaceId=conversation.workspace_id,
        agentId=conversation.agent_id,
        createdById=conversation.created_by_id,
        title=conversation.title,
        isActive=conversation.is_active,
        createdAt=conversation.created_at,
        updatedAt=conversation.updated_at,
    )


def conversation_message_response(message: ConversationMessage) -> ConversationMessageRead:
    return ConversationMessageRead(
        id=message.id,
        conversationId=message.conversation_id,
        agentRunId=message.agent_run_id,
        role=message.role,
        content=message.content,
        parts=message.parts or text_parts(message.content),
        sequence=message.sequence,
        createdAt=message.created_at,
        updatedAt=message.updated_at,
    )


def agent_run_response(
    agent_run: AgentRun,
    usage_summary=None,
    *,
    trace_id: str = "",
    span_id: str = "",
) -> AgentRunRead:
    return AgentRunRead(
        id=agent_run.id,
        organizationId=agent_run.organization_id,
        workspaceId=agent_run.workspace_id,
        agentId=agent_run.agent_id,
        conversationId=agent_run.conversation_id,
        triggeredById=agent_run.triggered_by_id,
        triggerType=agent_run.trigger_type,
        status=agent_run.status,
        inputTokens=usage_summary.input_tokens if usage_summary is not None else 0,
        outputTokens=usage_summary.output_tokens if usage_summary is not None else 0,
        totalTokens=usage_summary.total_tokens if usage_summary is not None else 0,
        costUsd=usage_summary.cost_usd if usage_summary is not None else 0,
        toolCalls=usage_summary.tool_calls if usage_summary is not None else 0,
        traceId=trace_id,
        spanId=span_id,
        startedAt=agent_run.started_at,
        finishedAt=agent_run.finished_at,
        error=agent_run.error,
        createdAt=agent_run.created_at,
        updatedAt=agent_run.updated_at,
    )


def agent_run_step_response(step) -> AgentRunStepRead:
    return AgentRunStepRead(
        id=step.id,
        agentRunId=step.agent_run_id,
        mcpToolInvocationId=step.mcp_tool_invocation_id,
        sequence=step.sequence,
        stepType=step.step_type,
        status=step.status,
        title=step.title,
        payload=step.payload,
        createdAt=step.created_at,
        updatedAt=step.updated_at,
    )


def assigned_tool_response(row) -> AgentToolRead:
    assignment, tool_schema, installation = row
    if tool_schema.workspace_id is None:
        raise InvalidAgentToolAssignmentError("assigned tool has no workspace")
    return AgentToolRead(
        id=tool_schema.id,
        agentId=assignment.agent_id,
        toolSchemaId=tool_schema.id,
        installationId=assignment.installation_id,
        workspaceId=tool_schema.workspace_id,
        serverName=tool_schema.server_name,
        configName=installation.config_name,
        toolName=tool_schema.tool_name,
        title=tool_schema.title,
        description=tool_schema.description,
        inputSchema=tool_schema.input_schema,
        outputSchema=tool_schema.output_schema,
        annotations=tool_schema.annotations,
        createdAt=assignment.created_at,
    )


def server_assignment_responses(rows) -> list[AgentServerToolAssignmentRead]:
    assignments: dict[uuid.UUID, list[uuid.UUID | str]] = {}
    for server_assignment, tool_assignment in rows:
        selected = assignments.setdefault(server_assignment.installation_id, [])
        if tool_assignment.wildcard:
            selected[:] = [TOOL_ASSIGNMENT_WILDCARD]
        elif TOOL_ASSIGNMENT_WILDCARD not in selected and tool_assignment.tool_schema_id:
            selected.append(tool_assignment.tool_schema_id)
    return [
        AgentServerToolAssignmentRead(
            installationId=installation_id,
            toolSchemaIds=tool_schema_ids,
        )
        for installation_id, tool_schema_ids in assignments.items()
    ]
