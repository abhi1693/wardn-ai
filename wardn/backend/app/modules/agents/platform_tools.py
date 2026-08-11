import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import repository as agent_repository
from app.modules.agents.models import (
    Agent,
    AgentMCPServerAssignment,
    AgentMCPToolAssignment,
    AgentToolApproval,
)
from app.modules.agents.tool_execution import tool_execution_result
from app.modules.agents.types import (
    FAILURE_TOOL_NOT_INSTALLED,
    AgentToolCall,
    AgentToolExecutionResult,
)
from app.modules.mcp_gateway import repository as mcp_gateway_repository
from app.modules.mcp_registry.models import MCPServerInstallation, MCPServerToolSchema
from app.modules.observability import service as observability_service
from app.modules.scheduled_tasks.models import (
    WorkspaceScheduledTask,
    WorkspaceScheduledTaskRun,
)

ASK_WARDN_PLATFORM_TOOL_NAME = "inspect_wardn_platform"
ASK_WARDN_PLATFORM_FOCUSES = {
    "overview",
    "mcp_failures",
    "production_access",
    "pending_approvals",
    "workspace_changes",
    "scheduled_failures",
}
PRODUCTION_HINT_PATTERN = re.compile(r"\b(prod|production|prd|live)\b", re.IGNORECASE)


def ask_wardn_platform_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "name": ASK_WARDN_PLATFORM_TOOL_NAME,
        "description": (
            "Inspect read-only Wardn platform state for this workspace. Use this before "
            "answering questions about MCP failures, production tool access, pending "
            "approvals, today's workspace changes, scheduled task failures, unhealthy "
            "runtimes, or recent agent activity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": sorted(ASK_WARDN_PLATFORM_FOCUSES),
                    "default": "overview",
                    "description": "Platform area to inspect.",
                },
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 30,
                    "default": 1,
                    "description": (
                        "Lookback window in days for recent runs, changes, and failures."
                    ),
                },
            },
            "additionalProperties": False,
        },
    }


async def execute_ask_wardn_platform_tool(
    session: AsyncSession,
    tool_call: AgentToolCall,
    *,
    organization_id: uuid.UUID | None,
    workspace_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> AgentToolExecutionResult:
    if organization_id is None or workspace_id is None:
        return tool_execution_result(
            ASK_WARDN_PLATFORM_TOOL_NAME,
            f"Tool {ASK_WARDN_PLATFORM_TOOL_NAME} failed: workspace scope is required.",
            failure_reason=FAILURE_TOOL_NOT_INSTALLED,
        )

    focus = str(tool_call.arguments.get("focus") or "overview")
    if focus not in ASK_WARDN_PLATFORM_FOCUSES:
        focus = "overview"
    days = bounded_days(tool_call.arguments.get("days"))
    now = datetime.now(UTC)
    start_date = now.date() - timedelta(days=days - 1)
    started_at = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    dashboard = await observability_service.workspace_observability_dashboard(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=now.date(),
        breakdown_limit=8,
    )
    payload = {
        "tool": ASK_WARDN_PLATFORM_TOOL_NAME,
        "focus": focus,
        "window": {
            "days": days,
            "startedAt": started_at.isoformat(),
            "endedAt": now.isoformat(),
        },
        "summary": {
            "healthScore": dashboard.summary.health_score,
            "agentRuns": dashboard.summary.agent_runs,
            "failedAgentRuns": dashboard.summary.failed_agent_runs,
            "runningAgentRuns": dashboard.summary.running_agent_runs,
            "failedModelRequests": dashboard.summary.failed_requests,
            "toolCalls": dashboard.summary.tool_calls,
            "failedToolCalls": dashboard.summary.failed_tool_calls,
            "runtimeSessionsNeedingAttention": (
                dashboard.summary.runtime_sessions_needing_attention
            ),
        },
        "attention": [
            {
                "label": item.label,
                "detail": item.detail,
                "severity": item.severity,
                "href": item.href,
            }
            for item in dashboard.attention
        ],
        "recentRuns": [
            {
                "id": str(run.id),
                "agentId": str(run.agent_id),
                "agentName": run.agent_name,
                "status": run.status,
                "triggerType": run.trigger_type,
                "startedAt": run.started_at.isoformat(),
                "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
                "requests": run.requests,
                "failedRequests": run.failed_requests,
                "toolCalls": run.tool_calls,
                "failedToolCalls": run.failed_tool_calls,
                "error": run.error,
                "href": f"agent-runs/{run.id}",
            }
            for run in dashboard.recent_runs[:8]
        ],
    }
    if focus in {"overview", "mcp_failures"}:
        payload["mcpFailures"] = failed_mcp_tool_rows(dashboard.top_tools)
    if focus in {"overview", "pending_approvals"}:
        payload["pendingApprovals"] = await pending_approval_rows(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            user_id=user_id,
            limit=10,
        )
    if focus in {"overview", "production_access"}:
        payload["productionAccess"] = await production_access_rows(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            limit=12,
        )
    if focus in {"overview", "workspace_changes"}:
        payload["recentChanges"] = await recent_change_rows(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            since=started_at,
            limit=12,
        )
    if focus in {"overview", "scheduled_failures"}:
        payload["scheduledFailures"] = await scheduled_failure_rows(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            since=started_at,
            limit=10,
        )

    output = json.dumps(payload, default=str, separators=(",", ":"))
    return tool_execution_result(
        ASK_WARDN_PLATFORM_TOOL_NAME,
        output,
        details={"platform": payload},
    )


def bounded_days(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    try:
        days = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(days, 30))


def failed_mcp_tool_rows(top_tools) -> list[dict[str, Any]]:
    return [
        {
            "serverName": tool.server_name,
            "toolName": tool.tool_name,
            "calls": tool.calls,
            "failed": tool.failed,
            "errorRate": tool.error_rate,
            "lastCalledAt": tool.last_called_at.isoformat() if tool.last_called_at else None,
        }
        for tool in top_tools
        if tool.failed > 0
    ][:8]


async def pending_approval_rows(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    limit: int,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    agent_result = await session.execute(
        select(AgentToolApproval, Agent.name)
        .join(Agent, Agent.id == AgentToolApproval.agent_id)
        .where(
            AgentToolApproval.organization_id == organization_id,
            AgentToolApproval.workspace_id == workspace_id,
            AgentToolApproval.status == "pending",
            or_(AgentToolApproval.expires_at.is_(None), AgentToolApproval.expires_at > now),
        )
        .order_by(AgentToolApproval.created_at.desc(), AgentToolApproval.id.desc())
        .limit(limit)
    )
    gateway_approvals = await mcp_gateway_repository.list_gateway_tool_approvals(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        status="pending",
        limit=limit,
    )
    agent_rows = [
        {
            "kind": "agent_tool",
            "id": str(approval.id),
            "agentId": str(approval.agent_id),
            "agentName": agent_name,
            "agentRunId": str(approval.agent_run_id) if approval.agent_run_id else None,
            "toolName": approval.tool_name,
            "requestedByCurrentUser": approval.requested_by_id == user_id if user_id else False,
            "createdAt": approval.created_at.isoformat(),
            "expiresAt": approval.expires_at.isoformat() if approval.expires_at else None,
            "href": (
                f"agents/{approval.agent_id}/approvals/{approval.id}"
                if approval.agent_id
                else ""
            ),
        }
        for approval, agent_name in agent_result.all()
    ]
    gateway_rows = [
        {
            "kind": "mcp_gateway",
            "id": str(approval.id),
            "installationId": str(approval.installation_id),
            "serverName": approval.server_name,
            "toolName": approval.tool_name,
            "createdAt": approval.created_at.isoformat(),
            "expiresAt": approval.expires_at.isoformat() if approval.expires_at else None,
            "href": "install",
        }
        for approval in gateway_approvals
    ]
    return {
        "count": len(agent_rows) + len(gateway_rows),
        "agentToolApprovals": agent_rows,
        "mcpGatewayApprovals": gateway_rows,
    }


async def production_access_rows(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    limit: int,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(Agent, MCPServerInstallation, MCPServerToolSchema)
        .join(AgentMCPServerAssignment, AgentMCPServerAssignment.agent_id == Agent.id)
        .join(
            MCPServerInstallation,
            MCPServerInstallation.id == AgentMCPServerAssignment.installation_id,
        )
        .join(
            AgentMCPToolAssignment,
            AgentMCPToolAssignment.server_assignment_id == AgentMCPServerAssignment.id,
        )
        .join(
            MCPServerToolSchema,
            or_(
                and_(
                    AgentMCPToolAssignment.wildcard.is_(False),
                    MCPServerToolSchema.id == AgentMCPToolAssignment.tool_schema_id,
                ),
                and_(
                    AgentMCPToolAssignment.wildcard.is_(True),
                    MCPServerToolSchema.installation_id == MCPServerInstallation.id,
                ),
            ),
        )
        .where(
            Agent.organization_id == organization_id,
            or_(Agent.workspace_id == workspace_id, Agent.workspace_id.is_(None)),
            Agent.is_active.is_(True),
            MCPServerInstallation.workspace_id == workspace_id,
            MCPServerInstallation.status == "enabled",
            MCPServerToolSchema.is_active.is_(True),
        )
        .order_by(Agent.name.asc(), MCPServerInstallation.config_name.asc())
        .limit(300)
    )
    grouped: dict[str, dict[str, Any]] = {}
    for agent, installation, tool in result.all():
        text = " ".join(
            [
                agent.name,
                agent.description,
                installation.server_name,
                installation.config_name,
                tool.tool_name,
                tool.title or "",
                tool.description or "",
            ]
        )
        if not PRODUCTION_HINT_PATTERN.search(text):
            continue
        key = str(agent.id)
        row = grouped.setdefault(
            key,
            {
                "agentId": key,
                "agentName": agent.name,
                "scope": agent.scope,
                "matchedBy": "name/config/tool text contains prod, production, prd, or live",
                "servers": {},
            },
        )
        server_key = f"{installation.server_name}:{installation.config_name}"
        server = row["servers"].setdefault(
            server_key,
            {
                "serverName": installation.server_name,
                "configuredTarget": installation.config_name,
                "tools": [],
            },
        )
        if len(server["tools"]) < 6:
            server["tools"].append(tool.tool_name)
    rows = []
    for row in grouped.values():
        rows.append({**row, "servers": list(row["servers"].values())})
    return rows[:limit]


async def recent_change_rows(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    since: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    rows = await agent_repository.list_recent_workspace_agent_run_steps(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        limit=limit * 3,
    )
    changes = []
    for step, run, agent in rows:
        if step.created_at < since:
            continue
        changes.append(
            {
                "agentRunId": str(run.id),
                "agentName": agent.name,
                "stepType": step.step_type,
                "status": step.status,
                "title": step.title,
                "createdAt": step.created_at.isoformat(),
                "href": f"agent-runs/{run.id}",
            }
        )
        if len(changes) >= limit:
            break
    return changes


async def scheduled_failure_rows(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    since: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    failed_count = func.count(WorkspaceScheduledTaskRun.id).filter(
        WorkspaceScheduledTaskRun.status.in_(("failed", "delivery_failed"))
    )
    result = await session.execute(
        select(
            WorkspaceScheduledTask,
            failed_count.label("recent_failed_runs"),
            func.max(WorkspaceScheduledTaskRun.finished_at).label("last_failed_at"),
        )
        .outerjoin(
            WorkspaceScheduledTaskRun,
            and_(
                WorkspaceScheduledTaskRun.task_id == WorkspaceScheduledTask.id,
                WorkspaceScheduledTaskRun.created_at >= since,
            ),
        )
        .where(
            WorkspaceScheduledTask.organization_id == organization_id,
            WorkspaceScheduledTask.workspace_id == workspace_id,
            WorkspaceScheduledTask.is_active.is_(True),
            or_(
                WorkspaceScheduledTask.last_status.in_(("failed", "delivery_failed")),
                WorkspaceScheduledTask.last_error != "",
            ),
        )
        .group_by(WorkspaceScheduledTask.id)
        .order_by(desc("recent_failed_runs"), WorkspaceScheduledTask.updated_at.desc())
        .limit(limit)
    )
    return [
        {
            "taskId": str(task.id),
            "name": task.name,
            "lastStatus": task.last_status,
            "lastError": task.last_error,
            "lastRunAt": task.last_run_at.isoformat() if task.last_run_at else None,
            "recentFailedRuns": int(recent_failed_runs or 0),
            "lastFailedAt": last_failed_at.isoformat() if last_failed_at else None,
            "maxAttempts": task.max_attempts,
            "href": "scheduled-tasks",
        }
        for task, recent_failed_runs, last_failed_at in result.all()
    ]
