from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import Agent
from app.modules.mcp_runtime.models import MCPToolInvocation
from app.modules.observability import repository
from app.modules.observability.schemas import (
    MCPToolUsageListResponse,
    MCPToolUsageRead,
    MCPToolUsageSummary,
)
from app.modules.users.models import User


def user_display_name(user: User | None) -> str:
    return user.display_name if user is not None else ""


def tool_usage_read(
    invocation: MCPToolInvocation,
    user: User | None,
    agent: Agent | None,
) -> MCPToolUsageRead:
    return MCPToolUsageRead(
        id=invocation.id,
        organizationId=invocation.organization_id,
        workspaceId=invocation.workspace_id,
        runtimeSessionId=invocation.runtime_session_id,
        installationId=invocation.installation_id,
        userId=invocation.user_id,
        userEmail=user.email if user is not None else "",
        userDisplayName=user_display_name(user),
        agentId=invocation.agent_id,
        agentName=agent.name if agent is not None else "",
        agentRunId=invocation.agent_run_id,
        serverName=invocation.server_name,
        serverVersion=invocation.server_version,
        toolName=invocation.tool_name,
        status=invocation.status,
        startedAt=invocation.started_at,
        finishedAt=invocation.finished_at,
        durationMs=invocation.duration_ms,
        inputSizeBytes=invocation.input_size_bytes,
        outputSizeBytes=invocation.output_size_bytes,
        isError=invocation.is_error,
        error=invocation.error,
    )


def tool_usage_summary(invocations: list[MCPToolInvocation]) -> MCPToolUsageSummary:
    total = len(invocations)
    completed_durations = [
        invocation.duration_ms
        for invocation in invocations
        if invocation.duration_ms is not None and invocation.duration_ms >= 0
    ]
    average_duration_ms = (
        round(sum(completed_durations) / len(completed_durations))
        if completed_durations
        else None
    )
    failed = sum(
        1
        for invocation in invocations
        if invocation.status == "failed" or invocation.is_error
    )
    return MCPToolUsageSummary(
        total=total,
        succeeded=sum(
            1
            for invocation in invocations
            if invocation.status == "succeeded" and not invocation.is_error
        ),
        failed=failed,
        running=sum(1 for invocation in invocations if invocation.status == "running"),
        attributed=sum(
            1
            for invocation in invocations
            if invocation.user_id is not None
            or invocation.agent_id is not None
            or invocation.agent_run_id is not None
        ),
        unattributed=sum(
            1
            for invocation in invocations
            if invocation.user_id is None
            and invocation.agent_id is None
            and invocation.agent_run_id is None
        ),
        averageDurationMs=average_duration_ms,
    )


async def list_workspace_mcp_tool_usage(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    limit: int = 100,
) -> MCPToolUsageListResponse:
    rows = await repository.list_mcp_tool_usage(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit,
    )
    invocations = [invocation for invocation, _user, _agent in rows]
    return MCPToolUsageListResponse(
        summary=tool_usage_summary(invocations),
        toolCalls=[
            tool_usage_read(invocation, user, agent)
            for invocation, user, agent in rows
        ],
    )
