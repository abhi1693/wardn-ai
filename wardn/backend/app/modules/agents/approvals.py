import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents import repository
from app.modules.agents.approval_expiry import (
    agent_tool_approval_expires_at,
    agent_tool_approval_is_expired,
)
from app.modules.agents.approval_links import agent_tool_approval_url
from app.modules.agents.chat_orchestrator import (
    filter_agent_runtime_tools_for_guardrails,
    run_agent_chat,
)
from app.modules.agents.conversations import AgentSessionFactory, agent_stream_unit_of_work
from app.modules.agents.exceptions import AgentNotFoundError, InvalidAgentScopeError
from app.modules.agents.mappers import (
    conversation_message_response,
    sanitize_run_payload,
    text_parts,
)
from app.modules.agents.models import Agent, AgentToolApproval, ConversationMessage
from app.modules.agents.provider_clients import agent_runtime_tools, validate_provider_credential
from app.modules.agents.schemas import (
    AgentChatMessage,
    AgentChatRequest,
    AgentToolApprovalDecisionRequest,
    AgentToolApprovalDecisionResponse,
    AgentToolApprovalRead,
)
from app.modules.agents.tool_execution import action_review_payload, mcp_result_text
from app.modules.agents.types import (
    AgentChatTextEvent,
    AgentChatToolActivityEvent,
    AgentInstalledTool,
)
from app.modules.chat_providers import repository as chat_provider_repository
from app.modules.mcp_gateway.client import MCPGatewayUpstreamError
from app.modules.mcp_runtime.providers.kubernetes import KubernetesRuntimeProviderError
from app.modules.mcp_runtime.service import call_tool_with_isolated_tracking
from app.modules.organizations.models import OrganizationMembership, WorkspaceMembership
from app.modules.organizations.service import (
    WORKSPACE_ADMIN_ROLES,
    require_workspace_member,
    workspace_role_for_user,
)
from app.modules.users.models import User

logger = logging.getLogger(__name__)
AgentToolApprovalScheduler = Callable[[AsyncSession, AgentToolApproval, User], Awaitable[None]]
ApprovalCompletionCheckpoint = Callable[[], Awaitable[None]]
APPROVAL_EXPIRED_ERROR = "Tool approval expired before it was approved."


def installed_agent_tools(rows: list[tuple[Any, ...]]) -> dict[str, AgentInstalledTool]:
    return {
        str(tool_schema.id): AgentInstalledTool(
            tool_schema=tool_schema,
            installation=installation,
        )
        for tool_schema, installation in rows
    }


def approval_workspace_member_route_user_ids(config: Any) -> set[uuid.UUID]:
    if not isinstance(config, dict):
        return set()
    routes = config.get("approval_routes") or config.get("approvalRoutes") or []
    if not isinstance(routes, list):
        return set()
    user_ids: set[uuid.UUID] = set()
    for route in routes:
        if not isinstance(route, dict):
            continue
        route_type = str(route.get("route_type") or route.get("routeType") or "").strip()
        if route_type != "workspace_member":
            continue
        try:
            user_ids.add(uuid.UUID(str(route.get("user_id") or route.get("userId") or "")))
        except (TypeError, ValueError):
            continue
    return user_ids


def workspace_membership_context(
    value: Any,
) -> tuple[OrganizationMembership | None, WorkspaceMembership | None]:
    if not isinstance(value, tuple) or len(value) < 3:
        return None, None
    organization_membership = value[1]
    workspace_membership = value[2]
    return (
        organization_membership
        if isinstance(organization_membership, OrganizationMembership)
        else None,
        workspace_membership if isinstance(workspace_membership, WorkspaceMembership) else None,
    )


async def user_can_access_chat_provider_approval(
    session: AsyncSession,
    user: User,
    approval: AgentToolApproval,
    *,
    organization_membership: OrganizationMembership | None,
    workspace_membership: WorkspaceMembership | None,
) -> bool:
    if approval.conversation_id is None:
        return False
    thread_connection = await chat_provider_repository.get_thread_connection_for_conversation(
        session,
        organization_id=approval.organization_id,
        workspace_id=approval.workspace_id,
        conversation_id=approval.conversation_id,
    )
    if thread_connection is None:
        return False
    _thread, connection = thread_connection
    selected_user_ids = approval_workspace_member_route_user_ids(connection.config)
    role = workspace_role_for_user(user, organization_membership, workspace_membership)
    if selected_user_ids:
        return user.id in selected_user_ids or role in WORKSPACE_ADMIN_ROLES
    return role in WORKSPACE_ADMIN_ROLES


async def ensure_agent_tool_approval_access(
    session: AsyncSession,
    user: User,
    approval: AgentToolApproval,
    *,
    organization_membership: OrganizationMembership | None,
    workspace_membership: WorkspaceMembership | None,
) -> None:
    if not approval.requested_by_id or approval.requested_by_id == user.id or user.is_superuser:
        return
    if await user_can_access_chat_provider_approval(
        session,
        user,
        approval,
        organization_membership=organization_membership,
        workspace_membership=workspace_membership,
    ):
        return
    raise InvalidAgentScopeError("tool approval belongs to another user")


def conversation_message_to_chat_message(message: ConversationMessage) -> AgentChatMessage:
    return AgentChatMessage(
        role=message.role,
        parts=message.parts or text_parts(message.content),
    )


def approval_continuation_prompt(approval: AgentToolApproval) -> str:
    result = approval.result.strip() or "(no tool output)"
    return (
        "The user approved the pending MCP tool call. Continue the assistant response using "
        "the approved tool result. Do not ask for approval again for this completed call.\n\n"
        f"Tool: {approval.tool_name}\n"
        f"Result:\n{result}"
    )


def agent_tool_approval_read(
    approval: AgentToolApproval,
    *,
    action_review: dict[str, Any] | None = None,
) -> AgentToolApprovalRead:
    return AgentToolApprovalRead(
        id=approval.id,
        organization_id=approval.organization_id,
        workspace_id=approval.workspace_id,
        agent_id=approval.agent_id,
        conversation_id=approval.conversation_id,
        agent_run_id=approval.agent_run_id,
        requested_by_id=approval.requested_by_id,
        decided_by_id=approval.decided_by_id,
        installation_id=approval.installation_id,
        tool_schema_id=approval.tool_schema_id,
        tool_call_id=approval.tool_call_id,
        tool_name=approval.tool_name,
        arguments=approval.arguments,
        status=approval.status,
        result=approval.result,
        error=approval.error,
        expires_at=agent_tool_approval_expires_at(approval),
        approval_url=agent_tool_approval_url(
            organization_id=approval.organization_id,
            workspace_id=approval.workspace_id,
            agent_id=approval.agent_id,
            approval_id=approval.id,
        ),
        action_review=action_review,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


async def approval_action_review(
    session: AsyncSession,
    approval: AgentToolApproval,
    *,
    agent: Agent,
) -> dict[str, Any] | None:
    runtime_rows = await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    runtime_tools = agent_runtime_tools(runtime_rows)
    tool = next(
        (
            candidate
            for candidate in runtime_tools.values()
            if candidate.installation.id == approval.installation_id
            and candidate.tool_schema.id == approval.tool_schema_id
        ),
        None,
    )
    if tool is None:
        return None
    return action_review_payload(
        approval=approval,
        tool=tool,
        decision_details={},
    )


async def get_agent_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
) -> AgentToolApprovalRead:
    access_context = await require_workspace_member(session, user, organization_id, workspace_id)
    organization_membership, workspace_membership = workspace_membership_context(access_context)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    approval = await repository.get_tool_approval(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        approval_id=approval_id,
        for_update=True,
    )
    if approval is None:
        raise AgentNotFoundError("tool approval not found")
    await ensure_agent_tool_approval_access(
        session,
        user,
        approval,
        organization_membership=organization_membership,
        workspace_membership=workspace_membership,
    )
    return agent_tool_approval_read(
        approval,
        action_review=await approval_action_review(session, approval, agent=agent),
    )


async def generate_approval_continuation_message(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent: Agent,
    approval: AgentToolApproval,
    *,
    session_factory: AgentSessionFactory | None = None,
) -> ConversationMessage | None:
    if approval.conversation_id is None or approval.status != "completed":
        return None
    if agent.provider_credential_id is None or not agent.model_name:
        return None
    credential = await validate_provider_credential(
        session,
        user,
        organization_id,
        agent_workspace_id=agent.workspace_id,
        provider_credential_id=agent.provider_credential_id,
    )
    if credential is None:
        return None
    messages = await repository.list_conversation_messages(
        session,
        conversation_id=approval.conversation_id,
    )
    chat_messages = [conversation_message_to_chat_message(message) for message in messages]
    chat_messages.append(
        AgentChatMessage(role="user", parts=text_parts(approval_continuation_prompt(approval)))
    )
    installed_tools = installed_agent_tools(
        await repository.list_workspace_available_tools(session, workspace_id=workspace_id)
    )
    runtime_tools = agent_runtime_tools(
        await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
    )
    guardrail_filter = await filter_agent_runtime_tools_for_guardrails(
        session,
        runtime_tools,
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent=agent,
        installed_tools=installed_tools,
    )
    agent_run = None
    if approval.agent_run_id is not None:
        agent_run = await repository.get_agent_run(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_run_id=approval.agent_run_id,
        )
    conversation = await repository.get_workspace_conversation(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        conversation_id=approval.conversation_id,
        include_inactive=True,
    )
    stream = run_agent_chat(
        agent,
        credential,
        AgentChatRequest(id=str(approval.conversation_id), messages=chat_messages),
        guardrail_filter,
        user=user,
        organization_id=organization_id,
        workspace_id=workspace_id,
        conversation=conversation,
        agent_run=agent_run,
        session_factory=session_factory,
    )
    chunks: list[str] = []
    activity_parts: dict[str, dict[str, Any]] = {}
    async for event in stream:
        if isinstance(event, AgentChatTextEvent) and event.text:
            chunks.append(event.text)
            continue
        if isinstance(event, AgentChatToolActivityEvent):
            data: dict[str, Any] = {
                "toolName": event.tool_name,
                "status": event.status,
            }
            if event.arguments is not None:
                data["arguments"] = sanitize_run_payload(event.arguments)
            if event.error:
                data["error"] = event.error
            if event.failure_reason:
                data["failureReason"] = event.failure_reason
            if event.message:
                data["message"] = event.message
            if event.progress is not None:
                data["progress"] = event.progress
            if event.progress_token is not None:
                data["progressToken"] = event.progress_token
            if event.result:
                data["result"] = sanitize_run_payload(event.result)
            if event.details:
                previous = activity_parts.get(event.id, {}).get("data", {})
                previous_details = previous.get("details") if isinstance(previous, dict) else None
                data["details"] = sanitize_run_payload(
                    {
                        **(previous_details if isinstance(previous_details, dict) else {}),
                        **event.details,
                    }
                )
            if event.total is not None:
                data["total"] = event.total
            if event.approval:
                data["approval"] = sanitize_run_payload(event.approval)
            activity_parts[event.id] = {
                "type": "data-tool-activity",
                "id": event.id,
                "data": data,
            }
            if agent_run is not None:
                is_progress_update = event.status == "running" and (
                    event.progress is not None or event.message is not None
                )
                step_payload = {
                    "agent_run_id": agent_run.id,
                    "step_type": (
                        "tool_progress"
                        if is_progress_update
                        else "tool_call"
                        if event.status == "running"
                        else "tool_result"
                    ),
                    "status": event.status,
                    "title": event.tool_name,
                    "payload": sanitize_run_payload(data),
                }
                if session_factory is None:
                    await repository.append_agent_run_step(
                        session,
                        **step_payload,
                    )
                else:
                    async with agent_stream_unit_of_work(session_factory) as step_session:
                        await repository.append_agent_run_step(
                            step_session,
                            **step_payload,
                        )
    content = "".join(chunks).strip()
    parts = list(activity_parts.values())
    if content:
        parts.extend(text_parts(content))
    if not parts:
        return None
    async def write_assistant_message(write_session: AsyncSession) -> ConversationMessage:
        message = await repository.append_conversation_message(
            write_session,
            conversation_id=approval.conversation_id,
            role="assistant",
            content=content,
            parts=parts,
            agent_run_id=approval.agent_run_id,
        )
        if approval.agent_run_id is not None and content:
            await repository.append_agent_run_step(
                write_session,
                agent_run_id=approval.agent_run_id,
                step_type="model_output",
                status="succeeded",
                title="Assistant response",
                payload={"content": sanitize_run_payload(content)},
            )
        return message

    if session_factory is None:
        return await write_assistant_message(session)
    async with agent_stream_unit_of_work(session_factory) as write_session:
        return await write_assistant_message(write_session)


async def finish_agent_run_after_tool_approval(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_run_id: uuid.UUID,
    approval_status: str,
    approval_error: str,
) -> None:
    agent_run = await repository.get_agent_run(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_run_id=agent_run_id,
    )
    if agent_run is None:
        return
    run_status = "succeeded" if approval_status == "completed" else "failed"
    if approval_status == "completed":
        active_approvals = await repository.list_active_tool_approvals_for_agent_run(
            session,
            agent_run_id=agent_run.id,
        )
        if active_approvals:
            run_status = "waiting_confirmation"
    await repository.finish_agent_run(
        session,
        agent_run,
        status=run_status,
        error=approval_error,
    )


def agent_tool_approval_decision_response(
    approval: AgentToolApproval,
    *,
    assistant_message: ConversationMessage | None = None,
) -> AgentToolApprovalDecisionResponse:
    return AgentToolApprovalDecisionResponse(
        approval_id=approval.id,
        status=approval.status,
        tool_name=approval.tool_name,
        result=approval.result,
        error=approval.error,
        expires_at=agent_tool_approval_expires_at(approval),
        assistant_message=conversation_message_response(assistant_message)
        if assistant_message is not None
        else None,
    )


async def set_agent_tool_approval_running(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    approval: AgentToolApproval,
) -> None:
    approval.status = "running"
    approval.error = ""
    await session.flush()
    if approval.agent_run_id is not None:
        await repository.append_agent_run_step(
            session,
            agent_run_id=approval.agent_run_id,
            step_type="tool_approval",
            status="running",
            title=approval.tool_name,
            payload={"approvalId": str(approval.id), "decision": "approve"},
        )
        agent_run = await repository.get_agent_run(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            agent_run_id=approval.agent_run_id,
        )
        if agent_run is not None:
            await repository.mark_agent_run_running(session, agent_run)
    if approval.conversation_id is not None:
        await repository.update_conversation_tool_activity(
            session,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            data_update={"status": "running"},
        )


async def expire_agent_tool_approval(
    session: AsyncSession,
    approval: AgentToolApproval,
    *,
    error: str = APPROVAL_EXPIRED_ERROR,
) -> None:
    approval.status = "expired"
    approval.error = error
    await session.flush()
    if approval.agent_run_id is not None:
        await repository.append_agent_run_step(
            session,
            agent_run_id=approval.agent_run_id,
            step_type="tool_approval",
            status="expired",
            title=approval.tool_name,
            payload={"approvalId": str(approval.id), "error": error},
        )
    if approval.conversation_id is not None:
        await repository.update_conversation_tool_activity(
            session,
            conversation_id=approval.conversation_id,
            approval_id=approval.id,
            data_update={"status": "expired", "error": error},
        )
    if approval.agent_run_id is not None:
        agent_run = await repository.get_agent_run(
            session,
            organization_id=approval.organization_id,
            workspace_id=approval.workspace_id,
            agent_run_id=approval.agent_run_id,
        )
        if agent_run is not None:
            await repository.finish_agent_run(
                session,
                agent_run,
                status="failed",
                error=error,
            )


async def complete_agent_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    checkpoint_after_execution: ApprovalCompletionCheckpoint | None = None,
    session_factory: AgentSessionFactory | None = None,
) -> AgentToolApprovalDecisionResponse:
    access_context = await require_workspace_member(session, user, organization_id, workspace_id)
    organization_membership, workspace_membership = workspace_membership_context(access_context)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    approval = await repository.get_tool_approval(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise AgentNotFoundError("tool approval not found")
    await ensure_agent_tool_approval_access(
        session,
        user,
        approval,
        organization_membership=organization_membership,
        workspace_membership=workspace_membership,
    )
    if approval.status == "pending" and agent_tool_approval_is_expired(approval):
        await expire_agent_tool_approval(session, approval)
        return agent_tool_approval_decision_response(approval)
    if approval.status == "pending":
        await set_agent_tool_approval_running(
            session,
            organization_id=organization_id,
            workspace_id=workspace_id,
            approval=approval,
        )
    elif approval.status not in {"running", "completed"}:
        return agent_tool_approval_decision_response(approval)

    if approval.status == "running":
        runtime_rows = await repository.list_agent_tool_runtime_rows(session, agent_id=agent.id)
        runtime_tools = agent_runtime_tools(runtime_rows)
        tool = next(
            (
                candidate
                for candidate in runtime_tools.values()
                if candidate.installation.id == approval.installation_id
                and candidate.tool_schema.id == approval.tool_schema_id
            ),
            None,
        )
        if tool is None:
            approval.status = "failed"
            approval.error = "Tool is no longer assigned to this agent."
        else:
            try:
                result = await call_tool_with_isolated_tracking(
                    session,
                    tool.installation,
                    tool.server,
                    tool_name=tool.tool_schema.tool_name,
                    arguments=approval.arguments,
                    user_id=user.id,
                    agent_id=agent.id,
                    agent_run_id=approval.agent_run_id,
                )
                approval.status = "completed"
                approval.result = mcp_result_text(result)
                approval.error = ""
            except (MCPGatewayUpstreamError, KubernetesRuntimeProviderError) as exc:
                approval.status = "failed"
                approval.error = str(exc)
            except Exception as exc:
                logger.exception(
                    "Agent tool approval execution failed.",
                    extra={
                        "organization_id": str(organization_id),
                        "workspace_id": str(workspace_id),
                        "agent_id": str(agent_id),
                        "approval_id": str(approval_id),
                    },
                )
                approval.status = "failed"
                approval.error = str(exc)
        await session.flush()
        if approval.agent_run_id is not None:
            await repository.append_agent_run_step(
                session,
                agent_run_id=approval.agent_run_id,
                step_type="tool_approval",
                status=approval.status,
                title=approval.tool_name,
                payload=sanitize_run_payload(
                    {
                        "approvalId": str(approval.id),
                        "decision": "approve",
                        "result": approval.result,
                        "error": approval.error,
                    }
                ),
            )
        if approval.conversation_id is not None:
            update: dict[str, Any] = {"status": approval.status}
            if approval.result:
                update["result"] = sanitize_run_payload(approval.result)
            if approval.error:
                update["error"] = approval.error
            await repository.update_conversation_tool_activity(
                session,
                conversation_id=approval.conversation_id,
                approval_id=approval.id,
                data_update=update,
            )
        if checkpoint_after_execution is not None:
            await checkpoint_after_execution()
    assistant_message = None
    if approval.status == "completed":
        assistant_message = await generate_approval_continuation_message(
            session,
            user,
            organization_id,
            workspace_id,
            agent,
            approval,
            session_factory=session_factory,
        )
    if approval.agent_run_id is not None:
        if session_factory is None:
            await finish_agent_run_after_tool_approval(
                session,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_run_id=approval.agent_run_id,
                approval_status=approval.status,
                approval_error=approval.error,
            )
        else:
            async with agent_stream_unit_of_work(session_factory) as finish_session:
                await finish_agent_run_after_tool_approval(
                    finish_session,
                    organization_id=organization_id,
                    workspace_id=workspace_id,
                    agent_run_id=approval.agent_run_id,
                    approval_status=approval.status,
                    approval_error=approval.error,
                )
    return agent_tool_approval_decision_response(
        approval,
        assistant_message=assistant_message,
    )


async def enqueue_agent_tool_approval_resume(
    session: AsyncSession,
    approval: AgentToolApproval,
    user: User,
) -> None:
    job = await repository.enqueue_agent_run_resume_job(
        session,
        approval=approval,
        user_id=user.id,
    )
    if job is None:
        raise InvalidAgentScopeError("tool approval is not linked to an agent run")
    if approval.agent_run_id is not None:
        await repository.append_agent_run_step(
            session,
            agent_run_id=approval.agent_run_id,
            step_type="approval_resume_queued",
            status="queued",
            title=approval.tool_name,
            payload={
                "approvalId": str(approval.id),
                "resumeJobId": str(job.id),
            },
        )


async def decide_agent_tool_approval(
    session: AsyncSession,
    user: User,
    organization_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    approval_id: uuid.UUID,
    payload: AgentToolApprovalDecisionRequest,
    *,
    schedule_completion: AgentToolApprovalScheduler | None = None,
) -> AgentToolApprovalDecisionResponse:
    access_context = await require_workspace_member(session, user, organization_id, workspace_id)
    organization_membership, workspace_membership = workspace_membership_context(access_context)
    agent = await repository.get_agent(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    if agent is None:
        raise AgentNotFoundError("agent not found")
    approval = await repository.get_tool_approval(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        approval_id=approval_id,
    )
    if approval is None:
        raise AgentNotFoundError("tool approval not found")
    await ensure_agent_tool_approval_access(
        session,
        user,
        approval,
        organization_membership=organization_membership,
        workspace_membership=workspace_membership,
    )
    if approval.status == "pending" and agent_tool_approval_is_expired(approval):
        await expire_agent_tool_approval(session, approval)
        return agent_tool_approval_decision_response(approval)
    if approval.status != "pending":
        return agent_tool_approval_decision_response(approval)

    approval.decided_by_id = user.id
    if payload.decision == "deny":
        approval.status = "denied"
        approval.error = "Denied by user."
        await session.flush()
        if approval.agent_run_id is not None:
            await repository.append_agent_run_step(
                session,
                agent_run_id=approval.agent_run_id,
                step_type="tool_approval",
                status="denied",
                title=approval.tool_name,
                payload={"approvalId": str(approval.id), "decision": "deny"},
            )
        if approval.conversation_id is not None:
            await repository.update_conversation_tool_activity(
                session,
                conversation_id=approval.conversation_id,
                approval_id=approval.id,
                data_update={"status": "denied", "error": approval.error},
            )
        if approval.agent_run_id is not None:
            agent_run = await repository.get_agent_run(
                session,
                organization_id=organization_id,
                workspace_id=workspace_id,
                agent_run_id=approval.agent_run_id,
            )
            if agent_run is not None:
                await repository.finish_agent_run(
                    session,
                    agent_run,
                    status="denied",
                    error=approval.error,
                )
        return agent_tool_approval_decision_response(approval)

    await set_agent_tool_approval_running(
        session,
        organization_id=organization_id,
        workspace_id=workspace_id,
        approval=approval,
    )
    if schedule_completion is not None:
        await schedule_completion(session, approval, user)
        return agent_tool_approval_decision_response(approval)
    return await complete_agent_tool_approval(
        session,
        user,
        organization_id,
        workspace_id,
        agent_id,
        approval.id,
    )
