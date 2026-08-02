import asyncio
import json
import re
import threading
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import repository
from app.modules.agents.approval_links import agent_tool_approval_url
from app.modules.agents.conversations import AgentSessionFactory, agent_stream_unit_of_work
from app.modules.agents.mappers import sanitize_run_payload
from app.modules.agents.models import Agent, AgentRun, AgentToolApproval, WorkspaceConversation
from app.modules.agents.types import (
    FAILURE_TARGET_MISMATCH_BLOCKED,
    FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
    FAILURE_TOOL_INSTALLED_NOT_ASSIGNED,
    FAILURE_TOOL_RAN_UPSTREAM_REJECTED,
    FAILURE_TOOL_SELECTED_RUNTIME_FAILED,
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
from app.modules.mcp_runtime.service import call_tool_with_isolated_tracking
from app.modules.users.models import User

AGENT_TOOL_BLOCKED_PREFIX = "Tool blocked by guardrail:"
AGENT_TOOL_CONFIRMATION_PREFIX = "Tool requires confirmation:"
AGENT_TOOL_TARGET_SAFETY_PREFIX = "Tool blocked by target safety:"
AGENT_CHAT_TOOL_OUTPUT_MAX_CHARS = 40_000
AGENT_TOOL_PROGRESS_HEARTBEAT_SECONDS = 15.0

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
            failure_reason=FAILURE_TOOL_INSTALLED_NOT_ASSIGNED,
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
        decision_details = {
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
        if progress_callback is not None:
            progress_callback(
                {
                    "message": f"Policy result: {decision.mode}",
                    "details": {"policy": decision_details},
                }
            )
        if agent_run is not None:
            await repository.append_agent_run_step(
                session,
                agent_run_id=agent_run.id,
                step_type="guardrail_decision",
                status=decision.mode,
                title=tool.tool_schema.tool_name,
                payload=sanitize_run_payload(
                    decision_details
                ),
            )
        if decision.mode == GUARDRAIL_MODE_DENY:
            return tool_execution_result(
                tool.tool_schema.tool_name,
                f"{AGENT_TOOL_BLOCKED_PREFIX} {decision.message}",
                failure_reason=FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
                details={"policy": decision_details},
            )
        if decision.mode == GUARDRAIL_MODE_REQUIRE_CONFIRMATION:
            if agent is None:
                return tool_execution_result(
                    tool.tool_schema.tool_name,
                    f"{AGENT_TOOL_BLOCKED_PREFIX} confirmation requires an agent context",
                    failure_reason=FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
                    details={"policy": decision_details},
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
                details={
                    "policy": decision_details,
                    "actionReview": action_review_payload(
                        approval=approval,
                        tool=tool,
                        decision_details=decision_details,
                    ),
                },
                approval=tool_approval_payload_with_review(
                    approval,
                    tool,
                    decision_details=decision_details,
                ),
            )
        if decision.mode != GUARDRAIL_MODE_ALLOW:
            return tool_execution_result(
                tool.tool_schema.tool_name,
                f"{AGENT_TOOL_BLOCKED_PREFIX} unsupported guardrail decision",
                failure_reason=FAILURE_TOOL_ASSIGNED_BLOCKED_POLICY,
                details={"policy": decision_details},
            )
    target_safety_message = ambiguous_mutating_tool_target_message(
        tools,
        tool,
        request_meta=request_meta,
    )
    if target_safety_message:
        return tool_execution_result(
            tool.tool_schema.tool_name,
            f"{AGENT_TOOL_TARGET_SAFETY_PREFIX} {target_safety_message}",
            failure_reason=FAILURE_TARGET_MISMATCH_BLOCKED,
            details={
                "targetSafety": {
                    "message": target_safety_message,
                    "selectedTarget": target_label(tool),
                }
            },
        )
    try:
        if progress_callback is not None:
            progress_callback(
                {
                    "message": "Runtime selected.",
                    "details": {
                        "runtime": {
                            "provider": tool.installation.runtime_config.get("provider"),
                            "installType": tool.installation.install_type,
                            "installationId": str(tool.installation.id),
                            "serverName": tool.server.name,
                            "configuredTarget": tool.installation.config_name,
                        }
                    },
                }
            )
        result = await call_tool_with_isolated_tracking(
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
    except KubernetesRuntimeProviderError as exc:
        return tool_execution_result(
            tool.tool_schema.tool_name,
            f"Tool {tool.tool_schema.tool_name} failed: {exc}",
            failure_reason=FAILURE_TOOL_SELECTED_RUNTIME_FAILED,
            details={
                "runtime": {
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                    "installationId": str(tool.installation.id),
                    "serverName": tool.server.name,
                    "configuredTarget": tool.installation.config_name,
                }
            },
        )
    except MCPGatewayUpstreamError as exc:
        return tool_execution_result(
            tool.tool_schema.tool_name,
            f"Tool {tool.tool_schema.tool_name} failed: {exc}",
            failure_reason=FAILURE_TOOL_RAN_UPSTREAM_REJECTED,
            details={
                "upstream": {
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                    "installationId": str(tool.installation.id),
                    "serverName": tool.server.name,
                    "configuredTarget": tool.installation.config_name,
                }
            },
        )
    return tool_execution_result(
        tool.tool_schema.tool_name,
        mcp_result_text(result),
        details={
            "runtime": {
                "installationId": str(tool.installation.id),
                "serverName": tool.server.name,
                "configuredTarget": tool.installation.config_name,
            },
            "upstream": {"accepted": True},
        },
    )


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
        "approvalUrl": agent_tool_approval_url(
            organization_id=approval.organization_id,
            workspace_id=approval.workspace_id,
            agent_id=approval.agent_id,
            approval_id=approval.id,
        ),
    }


def action_review_payload(
    *,
    approval: AgentToolApproval,
    tool: AgentRuntimeTool,
    decision_details: dict[str, Any],
) -> dict[str, Any]:
    runtime_config = tool.installation.runtime_config or {}
    return {
        "targetConnection": {
            "serverName": tool.server.name,
            "serverVersion": tool.server.version,
            "installationId": str(tool.installation.id),
            "configurationName": tool.installation.config_name or "",
            "installType": tool.installation.install_type or "",
        },
        "targetEnvironment": {
            "configuredTarget": tool.installation.config_name,
            "provider": runtime_config.get("provider"),
            "runtimeKind": runtime_config.get("kind"),
        },
        "tool": {
            "name": tool.tool_schema.tool_name,
            "title": tool.tool_schema.title,
            "schemaId": str(tool.tool_schema.id),
            "serverName": tool.tool_schema.server_name,
        },
        "normalizedArguments": sanitize_run_payload(approval.arguments),
        "matchingPolicy": {
            "mode": decision_details.get("mode"),
            "policyId": decision_details.get("policyId"),
            "policyName": decision_details.get("policyName"),
            "message": decision_details.get("message"),
            "matchedPolicyIds": decision_details.get("matchedPolicyIds", []),
        },
    }


def tool_approval_payload_with_review(
    approval: AgentToolApproval,
    tool: AgentRuntimeTool,
    *,
    decision_details: dict[str, Any],
) -> dict[str, Any]:
    payload = tool_approval_payload(approval, tool)
    payload["actionReview"] = action_review_payload(
        approval=approval,
        tool=tool,
        decision_details=decision_details,
    )
    return payload


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
        failure_reason=progress_message(params.get("failureReason")),
        message=progress_message(params.get("message")),
        progress=progress_number(params.get("progress")),
        progress_token=progress_token_value(params.get("progressToken")),
        details=progress_details(params.get("details")),
        total=progress_number(params.get("total")),
    )


def tool_activity_status_for_output(tool_name: str, output: str) -> tuple[str, str | None]:
    failed_prefix = f"Tool {tool_name} failed:"
    if output.startswith(AGENT_TOOL_BLOCKED_PREFIX) or output.startswith(
        AGENT_TOOL_TARGET_SAFETY_PREFIX
    ):
        return "blocked", output
    if output.startswith(AGENT_TOOL_CONFIRMATION_PREFIX):
        return "requires_confirmation", output
    if output.startswith(failed_prefix):
        return "failed", output
    return "completed", None


def progress_message(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def progress_details(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


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
    failure_reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> AgentToolExecutionResult:
    status, error = tool_activity_status_for_output(tool_name, output)
    return AgentToolExecutionResult(
        output=output,
        status=status,
        error=error,
        failure_reason=failure_reason if error else None,
        result=None if error else output,
        details=details,
        approval=approval,
    )


def progress_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def ambiguous_mutating_tool_target_message(
    tools: dict[str, AgentRuntimeTool],
    selected_tool: AgentRuntimeTool,
    *,
    request_meta: dict[str, Any] | None = None,
) -> str:
    if tool_read_only_hint(selected_tool):
        return ""
    target_group = [
        tool
        for tool in tools.values()
        if tool.tool_schema.server_name == selected_tool.tool_schema.server_name
        and tool.tool_schema.tool_name == selected_tool.tool_schema.tool_name
    ]
    if len({tool.installation.id for tool in target_group}) <= 1:
        return ""
    requested_text = normalized_target_text((request_meta or {}).get("userMessage"))
    if requested_text:
        requested_targets = [
            tool for tool in target_group if target_matches_user_text(tool, requested_text)
        ]
        if requested_targets and selected_tool.installation.id not in {
            tool.installation.id for tool in requested_targets
        }:
            return (
                f"the latest user request appears to reference "
                f"{target_labels(requested_targets)}, but the selected target was "
                f"{target_label(selected_tool)}. The tool was not executed. Run read-only "
                f"discovery across the configured targets and choose the matching target before "
                f"running this write-capable tool."
            )
        if requested_targets:
            return ""
    if not default_like_config_name(selected_tool.installation.config_name):
        return ""
    targets = ", ".join(
        sorted(
            {
                target_label(tool)
                for tool in target_group
            }
        )
    )
    return (
        f"{selected_tool.tool_schema.tool_name} is available from multiple configured MCP "
        f"targets: {targets}. The selected target was the generic default target, so the tool was "
        f"not executed. Use read-only discovery first or select the exact configured target before "
        f"running this write-capable tool."
    )


def tool_read_only_hint(tool: AgentRuntimeTool) -> bool:
    annotations = tool.tool_schema.annotations
    return isinstance(annotations, dict) and annotations.get("readOnlyHint") is True


def target_label(tool: AgentRuntimeTool) -> str:
    return (
        f"{tool.installation.config_name} "
        f"({tool.tool_schema.server_name}, installation {tool.installation.id})"
    )


def target_labels(tools: list[AgentRuntimeTool]) -> str:
    return ", ".join(sorted({target_label(tool) for tool in tools}))


def normalized_target_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def target_matches_user_text(tool: AgentRuntimeTool, normalized_user_text: str) -> bool:
    user_tokens = set(normalized_user_text.split())
    for raw_value, min_token_length in (
        (tool.installation.config_name, 2),
        (tool.tool_schema.server_name, 3),
        (tool.server.name, 3),
    ):
        normalized = normalized_target_text(raw_value)
        if not normalized:
            continue
        if normalized in normalized_user_text:
            return True
        target_tokens = [
            token for token in normalized.split() if len(token) >= min_token_length
        ]
        if len(set(target_tokens) & user_tokens) >= 2:
            return True
    return False


def default_like_config_name(value: str) -> bool:
    return normalized_target_text(value) in {"", "default"}


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
    request_meta: dict[str, Any] | None = None,
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
            request_meta={**(request_meta or {}), "progressToken": progress_token},
            cancel_event=cancel_event,
            cancel_reason="App chat stream was cancelled.",
            progress_callback=progress_callback,
        )
    )

    try:
        while not task.done():
            progress_task = asyncio.create_task(progress_queue.get())
            heartbeat_task = asyncio.create_task(
                asyncio.sleep(max(AGENT_TOOL_PROGRESS_HEARTBEAT_SECONDS, 0.001))
            )
            done, pending = await asyncio.wait(
                {task, progress_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            pending_helpers = pending - {task}
            for pending_task in pending_helpers:
                pending_task.cancel()
            for pending_task in pending_helpers:
                with suppress(asyncio.CancelledError):
                    await pending_task
            if progress_task in done:
                yield progress_activity_event(
                    activity_id=activity_id,
                    tool_name=tool_name,
                    params=progress_task.result(),
                )
            if heartbeat_task in done and not task.done():
                yield progress_activity_event(
                    activity_id=activity_id,
                    tool_name=tool_name,
                    params={
                        "message": "Waiting for runtime result.",
                        "progressToken": progress_token,
                    },
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
