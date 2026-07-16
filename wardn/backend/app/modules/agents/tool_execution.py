import asyncio
import json
import threading
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import repository
from app.modules.agents.conversations import AgentSessionFactory, agent_stream_unit_of_work
from app.modules.agents.mappers import sanitize_run_payload
from app.modules.agents.models import Agent, AgentRun, AgentToolApproval, WorkspaceConversation
from app.modules.agents.types import (
    AgentChatToolActivityEvent,
    AgentRuntimeTool,
    AgentToolCall,
    AgentToolExecutionResult,
)
from app.modules.guardrails.service import (
    GUARDRAIL_MODE_ALLOW,
    GUARDRAIL_MODE_DENY,
    GUARDRAIL_MODE_REQUIRE_CONFIRMATION,
    GuardrailEvaluationContext,
    evaluate_tool_call_guardrails,
)
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_runtime.providers.kubernetes import KubernetesRuntimeProviderError
from app.modules.mcp_runtime.service import call_tool_with_tracking
from app.modules.users.models import User

AGENT_TOOL_BLOCKED_PREFIX = "Tool blocked by guardrail:"
AGENT_TOOL_CONFIRMATION_PREFIX = "Tool requires confirmation:"
AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS = 40_000

async def _execute_agent_tool_call(
    session: AsyncSession,
    tools: dict[str, AgentRuntimeTool],
    tool_call: AgentToolCall,
    *,
    user: User | None = None,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    agent: Agent | None = None,
    conversation: WorkspaceConversation | None = None,
    agent_run: AgentRun | None = None,
    request_meta: dict[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
    cancel_reason: str = "Tool call cancelled.",
    progress_callback=None,
) -> AgentToolExecutionResult:
    tool = tools.get(tool_call.name)
    if tool is None:
        return tool_execution_result(
            tool_call.name,
            f"Tool {tool_call.name} is not assigned to this agent.",
        )
    if organization_id is not None:
        decision = await evaluate_tool_call_guardrails(
            session,
            GuardrailEvaluationContext(
                organization_id=organization_id,
                workspace_id=workspace_id or tool.installation.workspace_id,
                user_id=user.id if user else None,
                agent_id=agent.id if agent else None,
                conversation_id=conversation.id if conversation else None,
                agent_run_id=agent_run.id if agent_run else None,
                installation_id=tool.installation.id,
                tool_schema_id=tool.tool_schema.id,
                server_name=tool.server.name,
                tool_name=tool.tool_schema.tool_name,
                arguments=tool_call.arguments,
            ),
        )
        if agent_run is not None:
            await repository.append_agent_run_step(
                session,
                agent_run_id=agent_run.id,
                step_type="guardrail_decision",
                status=decision.mode,
                title=tool.tool_schema.tool_name,
                payload=sanitize_run_payload(
                    {
                        "mode": decision.mode,
                        "policyId": str(decision.policy_id) if decision.policy_id else None,
                        "policyName": decision.policy_name,
                        "matchedPolicyIds": [
                            str(policy_id) for policy_id in decision.matched_policy_ids
                        ],
                        "message": decision.message,
                        "toolName": tool.tool_schema.tool_name,
                        "serverName": tool.server.name,
                        "installationId": str(tool.installation.id),
                        "toolSchemaId": str(tool.tool_schema.id),
                        "arguments": tool_call.arguments,
                    }
                ),
            )
        if decision.mode == GUARDRAIL_MODE_DENY:
            return tool_execution_result(
                tool.tool_schema.tool_name,
                f"{AGENT_TOOL_BLOCKED_PREFIX} {decision.message}",
            )
        if decision.mode == GUARDRAIL_MODE_REQUIRE_CONFIRMATION:
            if agent is None:
                return tool_execution_result(
                    tool.tool_schema.tool_name,
                    f"{AGENT_TOOL_BLOCKED_PREFIX} confirmation requires an agent context",
                )
            approval = await repository.create_tool_approval(
                session,
                organization_id=organization_id,
                workspace_id=workspace_id or tool.installation.workspace_id,
                agent_id=agent.id,
                conversation_id=conversation.id if conversation else None,
                agent_run_id=agent_run.id if agent_run else None,
                requested_by_id=user.id if user else None,
                installation_id=tool.installation.id,
                tool_schema_id=tool.tool_schema.id,
                tool_call_id=tool_call.call_id,
                tool_name=tool.tool_schema.tool_name,
                arguments=tool_call.arguments,
            )
            return tool_execution_result(
                tool.tool_schema.tool_name,
                f"{AGENT_TOOL_CONFIRMATION_PREFIX} {decision.message}",
                approval=tool_approval_payload(approval, tool),
            )
        if decision.mode != GUARDRAIL_MODE_ALLOW:
            return tool_execution_result(
                tool.tool_schema.tool_name,
                f"{AGENT_TOOL_BLOCKED_PREFIX} unsupported guardrail decision",
            )
    try:
        result = await call_tool_with_tracking(
            session,
            tool.installation,
            tool.server,
            tool_name=tool.tool_schema.tool_name,
            arguments=tool_call.arguments,
            user_id=user.id if user else None,
            agent_id=agent.id if agent else None,
            agent_run_id=agent_run.id if agent_run else None,
            cancel_event=cancel_event,
            cancel_reason=cancel_reason,
            request_meta=request_meta,
            progress_callback=progress_callback,
        )
    except (MCPGatewayUpstreamError, KubernetesRuntimeProviderError) as exc:
        return tool_execution_result(
            tool.tool_schema.tool_name,
            f"Tool {tool.tool_schema.tool_name} failed: {exc}",
        )
    return tool_execution_result(tool.tool_schema.tool_name, mcp_result_text(result))


def progress_token_value(value: Any) -> str | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        return value
    return None


def tool_approval_payload(approval: AgentToolApproval, tool: AgentRuntimeTool) -> dict[str, Any]:
    return {
        "id": str(approval.id),
        "status": approval.status,
        "serverName": tool.server.name,
        "installationId": str(tool.installation.id),
        "toolSchemaId": str(tool.tool_schema.id),
        "toolName": tool.tool_schema.tool_name,
    }


def progress_activity_event(
    *,
    activity_id: str,
    tool_name: str,
    params: dict[str, Any],
) -> AgentChatToolActivityEvent:
    return AgentChatToolActivityEvent(
        id=activity_id,
        tool_name=tool_name,
        status="running",
        message=progress_message(params.get("message")),
        progress=progress_number(params.get("progress")),
        progress_token=progress_token_value(params.get("progressToken")),
        total=progress_number(params.get("total")),
    )


def tool_activity_status_for_output(tool_name: str, output: str) -> tuple[str, str | None]:
    failed_prefix = f"Tool {tool_name} failed:"
    if output.startswith(AGENT_TOOL_BLOCKED_PREFIX):
        return "blocked", output
    if output.startswith(AGENT_TOOL_CONFIRMATION_PREFIX):
        return "requires_confirmation", output
    if output.startswith(failed_prefix):
        return "failed", output
    return "completed", None


def progress_message(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def mcp_result_text(result: dict[str, Any]) -> str:
    text_parts = []
    content = result.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
    if text_parts:
        text = "\n".join(text_parts)
    else:
        text = json.dumps(result, separators=(",", ":"), sort_keys=True, default=str)
    if len(text) > AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS:
        return text[:AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS] + "\n[truncated]"
    return text


def tool_execution_result(
    tool_name: str,
    output: str,
    *,
    approval: dict[str, Any] | None = None,
) -> AgentToolExecutionResult:
    status, error = tool_activity_status_for_output(tool_name, output)
    return AgentToolExecutionResult(
        output=output,
        status=status,
        error=error,
        result=None if error else output,
        approval=approval,
    )


def progress_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


async def execute_agent_tool_call_with_progress(
    tools: dict[str, AgentRuntimeTool],
    tool_call: AgentToolCall,
    *,
    session_factory: AgentSessionFactory | None = None,
    activity_id: str,
    tool_name: str,
    user: User | None = None,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    agent: Agent | None = None,
    conversation: WorkspaceConversation | None = None,
    agent_run: AgentRun | None = None,
) -> AsyncGenerator[AgentChatToolActivityEvent | AgentToolExecutionResult, None]:
    progress_token = f"agent-tool:{tool_call.call_id}"
    cancel_event = threading.Event()
    progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def progress_callback(params: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(progress_queue.put_nowait, dict(params))

    task = asyncio.create_task(
        execute_agent_tool_call(
            tools,
            tool_call,
            session_factory=session_factory,
            user=user,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent=agent,
            conversation=conversation,
            agent_run=agent_run,
            request_meta={"progressToken": progress_token},
            cancel_event=cancel_event,
            cancel_reason="App chat stream was cancelled.",
            progress_callback=progress_callback,
        )
    )

    try:
        while not task.done():
            progress_task = asyncio.create_task(progress_queue.get())
            done, pending = await asyncio.wait(
                {task, progress_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            if progress_task in done:
                yield progress_activity_event(
                    activity_id=activity_id,
                    tool_name=tool_name,
                    params=progress_task.result(),
                )
    except asyncio.CancelledError:
        cancel_event.set()
        task.cancel()
        raise

    while not progress_queue.empty():
        yield progress_activity_event(
            activity_id=activity_id,
            tool_name=tool_name,
            params=progress_queue.get_nowait(),
        )
    yield task.result()


async def execute_agent_tool_call(
    tools: dict[str, AgentRuntimeTool],
    tool_call: AgentToolCall,
    *,
    session_factory: AgentSessionFactory | None = None,
    user: User | None = None,
    organization_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    agent: Agent | None = None,
    conversation: WorkspaceConversation | None = None,
    agent_run: AgentRun | None = None,
    request_meta: dict[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
    cancel_reason: str = "Tool call cancelled.",
    progress_callback=None,
) -> AgentToolExecutionResult:
    async with agent_stream_unit_of_work(session_factory) as session:
        return await _execute_agent_tool_call(
            session,
            tools,
            tool_call,
            user=user,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent=agent,
            conversation=conversation,
            agent_run=agent_run,
            request_meta=request_meta,
            cancel_event=cancel_event,
            cancel_reason=cancel_reason,
            progress_callback=progress_callback,
        )
